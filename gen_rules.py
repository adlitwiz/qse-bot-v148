"""Buat ulang qse_rules.py dari file Pine DASBOR. Pakai: python gen_rules.py QSE_v148_DASBOR.txt"""
import ast, re, sys
src = open(sys.argv[1] if len(sys.argv) > 1 else 'QSE_v148_DASBOR.txt', encoding='utf-8').read().splitlines()
def grab(name):
    for ln in src:
        if ln.startswith(name+"=array.from("):
            return ln[len(name)+len("=array.from("):-1]
    raise SystemExit("tidak ketemu "+name)
def split_top(s):
    out, d, cur, q = [], 0, "", False
    for ch in s:
        if ch == '"': q = not q
        if not q:
            if ch in "([": d += 1
            elif ch in ")]": d -= 1
            elif ch == "," and d == 0:
                out.append(cur.strip()); cur = ""; continue
        cur += ch
    out.append(cur.strip()); return out

class T(ast.NodeTransformer):
    def visit_BoolOp(self, n):
        self.generic_visit(n)
        op = ast.BitAnd() if isinstance(n.op, ast.And) else ast.BitOr()
        e = n.values[0]
        for v in n.values[1:]:
            e = ast.BinOp(left=e, op=op, right=v)
        return e
    def visit_UnaryOp(self, n):
        self.generic_visit(n)
        if isinstance(n.op, ast.Not):
            return ast.UnaryOp(op=ast.Invert(), operand=n.operand)
        return n
    def visit_Compare(self, n):
        self.generic_visit(n)
        assert len(n.ops) == 1, ast.dump(n)
        return n
    def visit_Subscript(self, n):
        self.generic_visit(n)
        k = n.slice
        return ast.Call(func=ast.Name(id="sh", ctx=ast.Load()), args=[n.value, k], keywords=[])
    def visit_Attribute(self, n):
        self.generic_visit(n)
        if isinstance(n.value, ast.Name) and n.value.id in ("ta", "math"):
            return ast.Name(id=n.value.id + "_" + n.attr, ctx=ast.Load())
        return n

def conv(e):
    t = ast.parse(e, mode="eval")
    t = ast.fix_missing_locations(T().visit(t))
    return ast.unparse(t.body)

out = ['"""QSE v148 - aturan 90 pola, DIHASILKAN OTOMATIS dari QSE_v148_DASBOR.txt (jangan edit manual)."""', ""]
for nmx in ["nm", "nrA"]:
    it = [x.strip('"') for x in split_top(grab(nmx))]
    assert len(it) == 90, (nmx, len(it))
    out.append(f"{nmx.upper()} = {it!r}")
for nmx in ["brkA"]:
    it = [x == "true" for x in split_top(grab(nmx))]
    assert len(it) == 90
    out.append(f"BRK = {it!r}")
fam = [int(x) for x in split_top(grab("famA"))]
assert len(fam) == 90
out.append(f"FAM = {fam!r}")
for nmx in ["cLa", "cSa", "lvL", "lvS"]:
    it = split_top(grab(nmx))
    assert len(it) == 90, (nmx, len(it))
    out.append("")
    out.append(f"def rules_{nmx}(v):")
    out.append("    g = v.__getitem__")
    names = set()
    exprs = [conv(e) for e in it]
    for e in exprs:
        for tok in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", e):
            names.add(tok)
    fn = {"sh", "nz", "na", "ta_highest", "ta_lowest", "math_abs", "math_avg"}
    for nme in sorted(names - fn):
        out.append(f"    {nme} = g({nme!r})")
    out.append("    sh, nz, na = v['sh'], v['nz'], v['na']")
    out.append("    ta_highest, ta_lowest, math_abs, math_avg = v['ta_highest'], v['ta_lowest'], v['math_abs'], v['math_avg']")
    out.append("    return [")
    for i, e in enumerate(exprs):
        out.append(f"        {e},  # {i}")
    out.append("    ]")
open("qse_rules.py", "w").write("\n".join(out) + "\n")
print("ok")
