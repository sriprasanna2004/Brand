import psycopg2

conn = psycopg2.connect('postgresql://postgres:bJRTFHQeRApaahgtNOmTdPJYKKokrPLo@switchyard.proxy.rlwy.net:12474/railway')
cur = conn.cursor()

enums = [
    ("leadstatus",    "'hot','warm','cold','opted_out'"),
    ("leadsource",    "'instagram_dm','instagram_comment','telegram'"),
    ("platform",      "'instagram','telegram'"),
    ("poststatus",    "'pending','approved','posted','failed'"),
    ("jobstatus",     "'pending','running','success','failed','dead_letter'"),
    ("sequencestatus","'sent','failed','opted_out'"),
]

for name, values in enums:
    try:
        cur.execute(f"CREATE TYPE {name} AS ENUM ({values})")
        print(f"Created: {name}")
    except psycopg2.errors.DuplicateObject:
        print(f"Already exists: {name}")
        conn.rollback()
    else:
        conn.commit()

cur.close()
conn.close()
print("Done!")
