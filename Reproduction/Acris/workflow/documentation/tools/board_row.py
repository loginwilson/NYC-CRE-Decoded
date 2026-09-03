import sqlite3, json
c = sqlite3.connect(r"D:\CRE Decoding System\Updates\Updates.db")
for r in c.execute("select source, phase, landed, rate_now, increase_now, rate, increase, pct_of_total, status, as_of from update_floors order by source, phase"):
    print(" | ".join(str(x) for x in r))
a = json.load(open(r"D:\CRE Decoding System\Updates\_board_truth.json", encoding="utf-8"))
print("anchor", a.get("counted_at"), "acris landed", format(a["sources"]["acris"]["landed"], ","), a["sources"]["acris"].get("counted"))
