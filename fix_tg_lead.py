import psycopg2
conn = psycopg2.connect('postgresql://postgres:bJRTFHQeRApaahgtNOmTdPJYKKokrPLo@switchyard.proxy.rlwy.net:12474/railway')
cur = conn.cursor()
cur.execute("UPDATE leads SET telegram_chat_id = '5454783507' WHERE ig_handle = 'tg_5454783507'")
cur.execute("SELECT ig_handle, telegram_chat_id, name FROM leads WHERE ig_handle = 'tg_5454783507'")
print("Updated:", cur.fetchone())
conn.commit()
conn.close()
print("Done")
