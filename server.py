#!/usr/bin/env python3
"""BillFlow Invoice API — Python stdlib only, zero dependencies."""
import http.server, json, sqlite3, configparser, urllib.parse
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
DB = BASE / 'invoice.db'
INI = BASE / 'settings.ini'

VALID_FIELDS = {
    'clients': {'company_name','contact_name','email','phone','address','tax_id','credit_limit'},
    'quotations': {'quote_number','client_id','issue_date','valid_until','subtotal','tax_amount','total','status','notes'},
    'invoices': {'invoice_number','client_id','quotation_id','issue_date','due_date','subtotal','tax_amount','total','amount_paid','balance','status','invoice_type','recurring','notes'},
    'receipts': {'receipt_number','invoice_id','client_id','amount','payment_date','payment_method','reference_number','notes'},
    'line_items': {'document_type','document_id','description','quantity','unit_price','discount_pct','tax_rate','line_total'},
    'payments': {'invoice_id','amount','payment_date','method','reference','status','gateway_txn_id'},
}

def get_conn():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL, contact_name TEXT, email TEXT, phone TEXT,
    address TEXT, tax_id TEXT, credit_limit REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_number TEXT NOT NULL UNIQUE, client_id INTEGER NOT NULL REFERENCES clients(id),
    issue_date TEXT NOT NULL, valid_until TEXT,
    subtotal REAL DEFAULT 0, tax_amount REAL DEFAULT 0, total REAL DEFAULT 0,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft','sent','accepted','rejected','expired','converted')),
    notes TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE, client_id INTEGER NOT NULL REFERENCES clients(id),
    quotation_id INTEGER REFERENCES quotations(id),
    issue_date TEXT NOT NULL, due_date TEXT NOT NULL,
    subtotal REAL DEFAULT 0, tax_amount REAL DEFAULT 0, total REAL DEFAULT 0,
    amount_paid REAL DEFAULT 0, balance REAL DEFAULT 0,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft','sent','paid','partial','overdue','void')),
    invoice_type TEXT DEFAULT 'standard' CHECK(invoice_type IN ('standard','proforma','commercial','credit_note','debit_note')),
    recurring INTEGER DEFAULT 0, notes TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_number TEXT NOT NULL UNIQUE, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),
    amount REAL NOT NULL, payment_date TEXT NOT NULL,
    payment_method TEXT DEFAULT 'bank', reference_number TEXT, notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type TEXT NOT NULL CHECK(document_type IN ('quotation','invoice')),
    document_id INTEGER NOT NULL, description TEXT NOT NULL,
    quantity REAL DEFAULT 1, unit_price REAL DEFAULT 0,
    discount_pct REAL DEFAULT 0, tax_rate REAL DEFAULT 8.0,
    line_total REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount REAL NOT NULL, payment_date TEXT NOT NULL,
    method TEXT DEFAULT 'bank' CHECK(method IN ('card','bank','check','paypal','wire','cash','crypto')),
    reference TEXT, status TEXT DEFAULT 'completed' CHECK(status IN ('completed','pending','failed','refunded')),
    gateway_txn_id TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tax_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, rate REAL NOT NULL, region TEXT,
    is_default INTEGER DEFAULT 0, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, entity_id INTEGER, action TEXT NOT NULL,
    details TEXT, timestamp TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_quo_client ON quotations(client_id);
CREATE INDEX IF NOT EXISTS idx_quo_status ON quotations(status);
CREATE INDEX IF NOT EXISTS idx_inv_client ON invoices(client_id);
CREATE INDEX IF NOT EXISTS idx_inv_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_inv_quo ON invoices(quotation_id);
CREATE INDEX IF NOT EXISTS idx_inv_due ON invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_inv_type ON invoices(invoice_type);
CREATE INDEX IF NOT EXISTS idx_rct_inv ON receipts(invoice_id);
CREATE INDEX IF NOT EXISTS idx_rct_client ON receipts(client_id);
CREATE INDEX IF NOT EXISTS idx_li_doc ON line_items(document_type, document_id);
CREATE INDEX IF NOT EXISTS idx_pay_inv ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_pay_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_log_entity ON activity_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_log_ts ON activity_log(timestamp DESC);
"""

def seed(conn):
    clients = [
        ('Nexus Technologies','Sarah Chen','sarah@nexustech.io','555-0101','100 Innovation Blvd, San Jose, CA','US-87-4521890',100000),
        ('Pinnacle Consulting','James Holloway','james@pinnacle.co','555-0102','45 Market St, San Francisco, CA','US-23-6789012',50000),
        ('Atlas Manufacturing','Maria Rodriguez','maria@atlasmfg.com','555-0103','800 Industrial Pkwy, Detroit, MI','US-45-1234567',150000),
        ('Horizon Media Group','David Park','david@horizonmedia.io','555-0104','220 Sunset Blvd, Los Angeles, CA','US-67-8901234',35000),
        ('Sterling & Associates','Emily Brooks','emily@sterling.law','555-0105','One Liberty Plaza, New York, NY','US-12-3456789',75000),
        ('Pacific Trade Co','Kevin Tanaka','kevin@pacifictrade.com','555-0106','500 Harbor Dr, Seattle, WA','US-34-5678901',200000),
        ('Quantum Solutions','Lisa Novak','lisa@quantumsol.dev','555-0107','70 Tech Circle, Austin, TX','US-56-7890123',40000),
        ('Redwood Capital','Michael Foster','michael@redwoodcap.com','555-0108','1 Financial Center, Boston, MA','US-78-9012345',250000),
    ]
    conn.executemany("INSERT INTO clients (company_name,contact_name,email,phone,address,tax_id,credit_limit) VALUES (?,?,?,?,?,?,?)", clients)

    quos = [
        ('QUO-1001',1,'2025-12-10','2026-01-10',41666.67,3333.33,45000,'converted','Annual support contract'),
        ('QUO-1002',2,'2025-12-15','2026-01-15',11574.07,925.93,12500,'converted','Strategy workshop series'),
        ('QUO-1003',3,'2026-01-20','2026-02-20',72222.22,5777.78,78000,'sent','Equipment upgrade Phase 2'),
        ('QUO-1004',4,'2026-01-05','2026-02-05',7592.59,607.41,8200,'rejected','Social media campaign'),
        ('QUO-1005',5,'2026-01-08','2026-02-08',14629.63,1170.37,15800,'converted','Legal retainer Q1'),
        ('QUO-1006',6,'2026-01-12','2026-02-12',85185.19,6814.81,92000,'converted','Bulk shipment contract'),
        ('QUO-1007',7,'2025-11-01','2025-12-01',5000,400,5400,'expired','App prototype'),
        ('QUO-1008',8,'2026-02-01','2026-03-01',31481.48,2518.52,34000,'sent','Portfolio analytics platform'),
        ('QUO-1009',1,'2026-02-10','2026-03-10',25925.93,2074.07,28000,'draft','Cloud migration Phase 3'),
        ('QUO-1010',3,'2026-02-05','2026-03-05',50925.93,4074.07,55000,'accepted','Assembly line automation'),
        ('QUO-1011',4,'2026-02-08','2026-03-08',10370.37,829.63,11200,'sent','Video production package'),
        ('QUO-1012',5,'2026-02-14','2026-03-14',18055.56,1444.44,19500,'draft','Compliance audit'),
    ]
    conn.executemany("INSERT INTO quotations (quote_number,client_id,issue_date,valid_until,subtotal,tax_amount,total,status,notes) VALUES (?,?,?,?,?,?,?,?,?)", quos)

    invs = [
        ('INV-1001',1,1,'2026-01-15','2026-02-14',41666.67,3333.33,45000,45000,0,'paid','standard',0,'From QUO-1001'),
        ('INV-1002',2,2,'2026-01-20','2026-02-19',11574.07,925.93,12500,12500,0,'paid','standard',0,'From QUO-1002'),
        ('INV-1003',5,3,'2026-01-15','2026-02-14',14629.63,1170.37,15800,15800,0,'paid','standard',0,'From QUO-1005'),
        ('INV-1004',6,4,'2026-01-18','2026-02-17',85185.19,6814.81,92000,70000,22000,'partial','standard',0,'From QUO-1006'),
        ('INV-1005',3,None,'2026-01-25','2026-02-24',57407.41,4592.59,62000,0,62000,'sent','proforma',0,'Direct proforma'),
        ('INV-1006',4,None,'2026-01-10','2026-02-09',9074.07,725.93,9800,0,9800,'overdue','standard',0,'Marketing services'),
        ('INV-1007',7,None,'2026-01-28','2026-02-27',6666.67,533.33,7200,7200,0,'paid','standard',0,'Dev sprint 4'),
        ('INV-1008',8,None,'2026-02-01','2026-03-03',37962.96,3037.04,41000,0,41000,'sent','commercial',0,'Financial modeling'),
        ('INV-1009',1,None,'2026-02-03','2026-03-05',35648.15,2851.85,38500,30000,8500,'partial','standard',1,'Monthly retainer'),
        ('INV-1010',2,None,'2026-02-05','2026-03-07',13148.15,1051.85,14200,14200,0,'paid','standard',0,'Feb consulting'),
        ('INV-1011',3,None,'2026-01-05','2026-02-04',50925.93,4074.07,55000,0,55000,'overdue','proforma',0,'Machinery order'),
        ('INV-1012',6,None,'2026-02-08','2026-03-10',26296.30,2103.70,28400,0,28400,'sent','commercial',0,'Logistics Q1'),
        ('INV-1013',4,None,'2026-02-12','2026-03-14',6018.52,481.48,6500,0,6500,'draft','standard',0,'Content creation'),
        ('INV-1014',5,None,'2026-02-07','2026-03-09',20370.37,1629.63,22000,22000,0,'paid','credit_note',0,'Overpayment refund'),
        ('INV-1015',8,None,'2026-02-10','2026-03-12',17222.22,1377.78,18600,0,18600,'sent','debit_note',0,'Additional charges'),
    ]
    conn.executemany("INSERT INTO invoices (invoice_number,client_id,quotation_id,issue_date,due_date,subtotal,tax_amount,total,amount_paid,balance,status,invoice_type,recurring,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", invs)

    rcts = [
        ('RCT-1001',1,1,45000,'2026-02-10','wire','WIR-20260210-001','Full payment'),
        ('RCT-1002',2,2,12500,'2026-02-15','bank','ACH-88291','Full payment'),
        ('RCT-1003',3,5,15800,'2026-02-12','check','CHK-4420','Full payment'),
        ('RCT-1004',4,6,50000,'2026-02-05','wire','WIR-20260205-002','Partial 1 of 2'),
        ('RCT-1005',7,7,7200,'2026-02-20','card','TXN-CC-99182','Full payment'),
        ('RCT-1006',9,1,20000,'2026-02-14','bank','ACH-90102','Partial 1'),
        ('RCT-1007',10,2,14200,'2026-02-28','paypal','PP-XK291A','Full payment'),
        ('RCT-1008',14,5,22000,'2026-02-18','wire','WIR-20260218-001','Credit note settled'),
        ('RCT-1009',4,6,20000,'2026-02-15','bank','ACH-91455','Partial 2 of 2'),
        ('RCT-1010',9,1,10000,'2026-02-25','card','TXN-CC-00291','Partial 2'),
    ]
    conn.executemany("INSERT INTO receipts (receipt_number,invoice_id,client_id,amount,payment_date,payment_method,reference_number,notes) VALUES (?,?,?,?,?,?,?,?)", rcts)

    # Line items for quotations
    q_items = [
        ('quotation',1,'Annual platform support',12,2500,0,8,30000),
        ('quotation',1,'Priority SLA upgrade',1,11666.67,0,8,11666.67),
        ('quotation',2,'Strategy workshop (per session)',5,1800,0,8,9000),
        ('quotation',2,'Research & analysis report',1,2574.07,0,8,2574.07),
        ('quotation',3,'CNC router upgrade',2,28000,0,8,56000),
        ('quotation',3,'Installation & calibration',1,16222.22,0,8,16222.22),
        ('quotation',5,'Legal retainer (monthly)',3,4200,0,8,12600),
        ('quotation',5,'Document review package',1,2029.63,0,8,2029.63),
        ('quotation',6,'Container shipping (40ft)',10,7500,0,8,75000),
        ('quotation',6,'Customs brokerage',1,10185.19,0,8,10185.19),
        ('quotation',8,'Analytics dashboard build',1,20000,0,8,20000),
        ('quotation',8,'Data pipeline setup',1,11481.48,0,8,11481.48),
    ]
    conn.executemany("INSERT INTO line_items (document_type,document_id,description,quantity,unit_price,discount_pct,tax_rate,line_total) VALUES (?,?,?,?,?,?,?,?)", q_items)

    # Line items for invoices
    i_items = [
        ('invoice',1,'Annual platform support',12,2500,0,8,30000),
        ('invoice',1,'Priority SLA upgrade',1,11666.67,0,8,11666.67),
        ('invoice',2,'Strategy workshop (per session)',5,1800,0,8,9000),
        ('invoice',2,'Research & analysis report',1,2574.07,0,8,2574.07),
        ('invoice',3,'Legal retainer (monthly)',3,4200,0,8,12600),
        ('invoice',3,'Document review package',1,2029.63,0,8,2029.63),
        ('invoice',4,'Container shipping (40ft)',10,7500,0,8,75000),
        ('invoice',4,'Customs brokerage',1,10185.19,0,8,10185.19),
        ('invoice',5,'Equipment inspection (proforma)',3,15000,5,8,42750),
        ('invoice',5,'Engineering assessment',1,14657.41,0,8,14657.41),
        ('invoice',6,'Social media management',1,5000,0,8,5000),
        ('invoice',6,'PPC campaign setup',1,4074.07,0,8,4074.07),
        ('invoice',7,'Sprint 4 development (40hrs)',40,150,0,8,6000),
        ('invoice',7,'QA testing',1,666.67,0,8,666.67),
        ('invoice',8,'Financial model (DCF)',1,25000,0,8,25000),
        ('invoice',8,'Market comp analysis',1,12962.96,0,8,12962.96),
        ('invoice',9,'Platform retainer (Feb)',1,25000,0,8,25000),
        ('invoice',9,'Bug fixes & patches',15,708.54,0,8,10628.15),
        ('invoice',10,'Consulting hours (Feb)',20,600,0,8,12000),
        ('invoice',10,'Travel expenses',1,1148.15,0,8,1148.15),
        ('invoice',11,'Assembly robot arm (proforma)',2,22000,0,8,44000),
        ('invoice',11,'Sensor array package',1,6925.93,0,8,6925.93),
        ('invoice',12,'Freight forwarding Q1',1,18000,0,8,18000),
        ('invoice',12,'Warehouse staging',1,8296.30,0,8,8296.30),
        ('invoice',13,'Blog content (10 articles)',10,450,0,8,4500),
        ('invoice',13,'Infographic design',3,506.17,0,8,1518.52),
        ('invoice',14,'Credit: Overbilled hours',1,20370.37,0,8,20370.37),
        ('invoice',15,'Late delivery surcharge',1,12000,0,8,12000),
        ('invoice',15,'Expedited processing fee',1,5222.22,0,8,5222.22),
    ]
    conn.executemany("INSERT INTO line_items (document_type,document_id,description,quantity,unit_price,discount_pct,tax_rate,line_total) VALUES (?,?,?,?,?,?,?,?)", i_items)

    pays = [
        (1,45000,'2026-02-10','wire','WIR-20260210-001','completed','GW-001'),
        (2,12500,'2026-02-15','bank','ACH-88291','completed','GW-002'),
        (3,15800,'2026-02-12','check','CHK-4420','completed',None),
        (4,50000,'2026-02-05','wire','WIR-20260205-002','completed','GW-003'),
        (4,20000,'2026-02-15','bank','ACH-91455','completed','GW-008'),
        (7,7200,'2026-02-20','card','TXN-CC-99182','completed','GW-004'),
        (9,20000,'2026-02-14','bank','ACH-90102','completed','GW-005'),
        (9,10000,'2026-02-25','card','TXN-CC-00291','completed','GW-006'),
        (10,14200,'2026-02-28','paypal','PP-XK291A','completed','GW-007'),
        (14,22000,'2026-02-18','wire','WIR-20260218-001','completed','GW-009'),
    ]
    conn.executemany("INSERT INTO payments (invoice_id,amount,payment_date,method,reference,status,gateway_txn_id) VALUES (?,?,?,?,?,?,?)", pays)

    taxes = [('Standard',8.0,'US',1,1),('Reduced',5.0,'US',0,1),('Zero',0.0,'Export',0,1),('State CA',6.25,'CA',0,1)]
    conn.executemany("INSERT INTO tax_rates (name,rate,region,is_default,active) VALUES (?,?,?,?,?)", taxes)

    logs = [
        ('quotation',1,'created','QUO-1001 created for Nexus Technologies','2025-12-10 09:00:00'),
        ('quotation',1,'sent','Emailed to sarah@nexustech.io','2025-12-10 09:30:00'),
        ('quotation',1,'accepted','Client accepted via portal','2025-12-28 14:20:00'),
        ('quotation',1,'converted','Converted to INV-1001','2026-01-15 10:00:00'),
        ('invoice',1,'created','INV-1001 from QUO-1001','2026-01-15 10:00:00'),
        ('invoice',1,'sent','Emailed to client','2026-01-15 10:15:00'),
        ('invoice',1,'paid','Full payment received via wire','2026-02-10 11:30:00'),
        ('receipt',1,'created','RCT-1001 generated','2026-02-10 11:31:00'),
        ('invoice',4,'created','INV-1004 from QUO-1006','2026-01-18 08:45:00'),
        ('invoice',4,'sent','Emailed to client','2026-01-18 09:00:00'),
        ('payment',4,'received','Partial $50,000 via wire','2026-02-05 14:00:00'),
        ('payment',5,'received','Partial $20,000 via bank','2026-02-15 10:00:00'),
        ('invoice',6,'created','INV-1006 direct invoice','2026-01-10 11:00:00'),
        ('invoice',6,'sent','Emailed to client','2026-01-10 11:15:00'),
        ('invoice',6,'overdue','Past due date 2026-02-09','2026-02-10 00:00:00'),
        ('invoice',11,'overdue','Past due date 2026-02-04','2026-02-05 00:00:00'),
        ('quotation',3,'created','QUO-1003 for Atlas Manufacturing','2026-01-20 13:00:00'),
        ('quotation',3,'sent','Emailed to maria@atlasmfg.com','2026-01-20 13:30:00'),
        ('invoice',13,'created','INV-1013 draft','2026-02-12 16:00:00'),
        ('invoice',14,'created','INV-1014 credit note issued','2026-02-07 09:00:00'),
    ]
    conn.executemany("INSERT INTO activity_log (entity_type,entity_id,action,details,timestamp) VALUES (?,?,?,?,?)", logs)

def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0:
        seed(conn)
        conn.commit()
    conn.close()

def read_ini():
    c = configparser.ConfigParser()
    c.read(str(INI))
    return {s: dict(c[s]) for s in c.sections()}

def write_ini_key(section, key, value):
    c = configparser.ConfigParser()
    c.read(str(INI))
    if not c.has_section(section):
        c.add_section(section)
    c.set(section, key, str(value))
    with open(str(INI), 'w') as f:
        c.write(f)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(BASE), **kw)

    def log_message(self, fmt, *args):
        if '/api/' in (args[0] if args else ''):
            super().log_message(fmt, *args)

    def _json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',len(body))
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        ln = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(ln)) if ln else {}

    def do_OPTIONS(self):
        self.send_response(204)
        for h,v in [('Access-Control-Allow-Origin','*'),('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS'),('Access-Control-Allow-Headers','Content-Type')]:
            self.send_header(h,v)
        self.end_headers()

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if not p.path.startswith('/api/'):
            return super().do_GET()
        parts = p.path.strip('/').split('/')
        res = parts[1] if len(parts)>1 else ''
        rid = parts[2] if len(parts)>2 else None
        qs = urllib.parse.parse_qs(p.query)
        conn = get_conn()
        try:
            if res == 'clients':
                self._json([dict(r) for r in conn.execute("SELECT * FROM clients ORDER BY company_name").fetchall()])
            elif res == 'quotations':
                self._json([dict(r) for r in conn.execute("SELECT q.*,c.company_name AS client_name FROM quotations q JOIN clients c ON q.client_id=c.id ORDER BY q.id DESC").fetchall()])
            elif res == 'invoices':
                self._json([dict(r) for r in conn.execute("SELECT i.*,c.company_name AS client_name,q.quote_number FROM invoices i JOIN clients c ON i.client_id=c.id LEFT JOIN quotations q ON i.quotation_id=q.id ORDER BY i.id DESC").fetchall()])
            elif res == 'receipts':
                self._json([dict(r) for r in conn.execute("SELECT r.*,c.company_name AS client_name,i.invoice_number FROM receipts r JOIN clients c ON r.client_id=c.id JOIN invoices i ON r.invoice_id=i.id ORDER BY r.id DESC").fetchall()])
            elif res == 'line_items':
                dt = qs.get('doc_type',[''])[0]
                di = qs.get('doc_id',['0'])[0]
                self._json([dict(r) for r in conn.execute("SELECT * FROM line_items WHERE document_type=? AND document_id=? ORDER BY id",(dt,di)).fetchall()])
            elif res == 'tax_rates':
                self._json([dict(r) for r in conn.execute("SELECT * FROM tax_rates ORDER BY id").fetchall()])
            elif res == 'activity_log':
                self._json([dict(r) for r in conn.execute("SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT 50").fetchall()])
            elif res == 'settings':
                self._json(read_ini())
            elif res == 'stats':
                s = {}
                s['total_invoiced'] = conn.execute("SELECT COALESCE(SUM(total),0) FROM invoices WHERE status!='void'").fetchone()[0]
                s['total_collected'] = conn.execute("SELECT COALESCE(SUM(amount_paid),0) FROM invoices").fetchone()[0]
                s['outstanding'] = conn.execute("SELECT COALESCE(SUM(balance),0) FROM invoices WHERE status IN ('sent','partial','overdue')").fetchone()[0]
                s['invoice_count'] = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
                s['quotation_count'] = conn.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]
                s['receipt_count'] = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
                s['overdue_count'] = conn.execute("SELECT COUNT(*) FROM invoices WHERE status='overdue'").fetchone()[0]
                s['avg_days_to_pay'] = round(conn.execute("SELECT COALESCE(AVG(julianday(r.payment_date)-julianday(i.issue_date)),0) FROM receipts r JOIN invoices i ON r.invoice_id=i.id").fetchone()[0],1)
                s['monthly'] = [dict(r) for r in conn.execute("SELECT strftime('%%Y-%%m',issue_date) AS month,SUM(total) AS invoiced,SUM(amount_paid) AS collected FROM invoices WHERE issue_date>=date('now','-12 months') GROUP BY month ORDER BY month").fetchall()]
                s['by_status'] = [dict(r) for r in conn.execute("SELECT status,COUNT(*) AS count,COALESCE(SUM(total),0) AS total FROM invoices GROUP BY status").fetchall()]
                s['by_client'] = [dict(r) for r in conn.execute("SELECT c.company_name,COALESCE(SUM(i.total),0) AS total FROM invoices i JOIN clients c ON i.client_id=c.id WHERE i.status!='void' GROUP BY i.client_id ORDER BY total DESC").fetchall()]
                s['aging'] = [dict(r) for r in conn.execute("""SELECT CASE WHEN julianday('now')-julianday(due_date)<=0 THEN 'Current' WHEN julianday('now')-julianday(due_date)<=15 THEN '1-15 days' WHEN julianday('now')-julianday(due_date)<=30 THEN '16-30 days' WHEN julianday('now')-julianday(due_date)<=60 THEN '31-60 days' WHEN julianday('now')-julianday(due_date)<=90 THEN '61-90 days' ELSE '90+ days' END AS bucket,COALESCE(SUM(balance),0) AS amount,COUNT(*) AS count FROM invoices WHERE balance>0 GROUP BY bucket""").fetchall()]
                s['by_type'] = [dict(r) for r in conn.execute("SELECT invoice_type,COUNT(*) AS count,COALESCE(SUM(total),0) AS total FROM invoices GROUP BY invoice_type").fetchall()]
                self._json(s)
            else:
                self._json({'error':'Not found'},404)
        finally:
            conn.close()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path)
        parts = p.path.strip('/').split('/')
        res = parts[1] if len(parts)>1 else ''
        rid = parts[2] if len(parts)>2 else None
        action = parts[3] if len(parts)>3 else None
        body = self._body()
        conn = get_conn()
        try:
            if res == 'quotations' and rid and action == 'convert':
                q = conn.execute("SELECT * FROM quotations WHERE id=?",(int(rid),)).fetchone()
                if not q: return self._json({'error':'Not found'},404)
                cfg = read_ini()
                pfx = cfg.get('general',{}).get('invoice_prefix','INV-')
                sfx = cfg.get('general',{}).get('invoice_suffix','')
                nxt = int(cfg.get('general',{}).get('next_invoice_num','1000'))
                inv_num = f"{pfx}{nxt:04d}{sfx}"
                conn.execute("INSERT INTO invoices (invoice_number,client_id,quotation_id,issue_date,due_date,subtotal,tax_amount,total,balance,status) VALUES (?,?,?,date('now'),date('now','+30 days'),?,?,?,?,'sent')",(inv_num,q['client_id'],int(rid),q['subtotal'],q['tax_amount'],q['total'],q['total']))
                inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                for it in conn.execute("SELECT * FROM line_items WHERE document_type='quotation' AND document_id=?",(int(rid),)).fetchall():
                    conn.execute("INSERT INTO line_items (document_type,document_id,description,quantity,unit_price,discount_pct,tax_rate,line_total) VALUES ('invoice',?,?,?,?,?,?,?)",(inv_id,it['description'],it['quantity'],it['unit_price'],it['discount_pct'],it['tax_rate'],it['line_total']))
                conn.execute("UPDATE quotations SET status='converted' WHERE id=?",(int(rid),))
                conn.execute("INSERT INTO activity_log (entity_type,entity_id,action,details) VALUES ('quotation',?,'converted',?)",(int(rid),f'Created {inv_num}'))
                write_ini_key('general','next_invoice_num',str(nxt+1))
                conn.commit()
                self._json({'ok':True,'invoice_id':inv_id,'invoice_number':inv_num})

            elif res == 'invoices' and rid and action == 'receipt':
                inv = conn.execute("SELECT * FROM invoices WHERE id=?",(int(rid),)).fetchone()
                if not inv: return self._json({'error':'Not found'},404)
                amt = body.get('amount', inv['balance'])
                method = body.get('payment_method','bank')
                cfg = read_ini()
                pfx = cfg.get('general',{}).get('receipt_prefix','RCT-')
                sfx = cfg.get('general',{}).get('receipt_suffix','')
                nxt = int(cfg.get('general',{}).get('next_receipt_num','1000'))
                rct_num = f"{pfx}{nxt:04d}{sfx}"
                conn.execute("INSERT INTO receipts (receipt_number,invoice_id,client_id,amount,payment_date,payment_method,reference_number) VALUES (?,?,?,?,date('now'),?,?)",(rct_num,int(rid),inv['client_id'],amt,method,body.get('reference','')))
                conn.execute("INSERT INTO payments (invoice_id,amount,payment_date,method,reference,status) VALUES (?,?,date('now'),?,?,'completed')",(int(rid),amt,method,body.get('reference','')))
                new_paid = inv['amount_paid']+amt
                new_bal = max(0, inv['total']-new_paid)
                new_st = 'paid' if new_bal<=0 else 'partial'
                conn.execute("UPDATE invoices SET amount_paid=?,balance=?,status=? WHERE id=?",(new_paid,new_bal,new_st,int(rid)))
                conn.execute("INSERT INTO activity_log (entity_type,entity_id,action,details) VALUES ('invoice',?,'receipt',?)",(int(rid),f'{rct_num} ${amt:.2f}'))
                write_ini_key('general','next_receipt_num',str(nxt+1))
                conn.commit()
                self._json({'ok':True,'receipt_number':rct_num})

            elif res in ('quotations','invoices','receipts','line_items'):
                valid = VALID_FIELDS.get(res,set())
                cols = [k for k in body if k in valid]
                if not cols: return self._json({'error':'No valid fields'},400)
                vals = [body[k] for k in cols]
                sql = f"INSERT INTO {res} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
                conn.execute(sql, vals)
                new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute("INSERT INTO activity_log (entity_type,entity_id,action,details) VALUES (?,?,?,?)",(res,new_id,'created',json.dumps(body,default=str)))
                conn.commit()
                self._json({'ok':True,'id':new_id})
            else:
                self._json({'error':'Invalid endpoint'},400)
        finally:
            conn.close()

    def do_PUT(self):
        p = urllib.parse.urlparse(self.path)
        parts = p.path.strip('/').split('/')
        res = parts[1] if len(parts)>1 else ''
        rid = parts[2] if len(parts)>2 else None
        body = self._body()
        conn = get_conn()
        try:
            if res == 'settings':
                sec = body.get('section','general')
                key = body.get('key','')
                val = body.get('value','')
                write_ini_key(sec, key, val)
                self._json({'ok':True})
            elif res in VALID_FIELDS and rid:
                valid = VALID_FIELDS[res]
                fields, values = [], []
                for k,v in body.items():
                    if k in valid:
                        fields.append(f"{k}=?")
                        values.append(v)
                if not fields: return self._json({'error':'No valid fields'},400)
                values.append(int(rid))
                conn.execute(f"UPDATE {res} SET {','.join(fields)} WHERE id=?", values)
                conn.execute("INSERT INTO activity_log (entity_type,entity_id,action,details) VALUES (?,?,?,?)",(res,int(rid),'updated',json.dumps(body,default=str)))
                conn.commit()
                self._json({'ok':True})
            else:
                self._json({'error':'Invalid'},400)
        finally:
            conn.close()

    def do_DELETE(self):
        p = urllib.parse.urlparse(self.path)
        parts = p.path.strip('/').split('/')
        res = parts[1] if len(parts)>1 else ''
        rid = parts[2] if len(parts)>2 else None
        if res not in VALID_FIELDS or not rid:
            return self._json({'error':'Invalid'},400)
        conn = get_conn()
        try:
            conn.execute(f"DELETE FROM {res} WHERE id=?", (int(rid),))
            conn.execute("INSERT INTO activity_log (entity_type,entity_id,action) VALUES (?,?,?)",(res,int(rid),'deleted'))
            conn.commit()
            self._json({'ok':True})
        finally:
            conn.close()

if __name__ == '__main__':
    init_db()
    srv = http.server.HTTPServer(('127.0.0.1', 8899), Handler)
    print(f"\n  BillFlow API running → http://127.0.0.1:8899\n  DB: {DB}\n  INI: {INI}\n")
    srv.serve_forever()
