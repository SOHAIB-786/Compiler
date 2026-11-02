"""RomanEng (.rc) compiler core: grammar + 4 generators (lexical, syntax, semantic, intermediate code)."""
import re
import io
import contextlib

# ───────────────────────── 1. GRAMMAR (single source of truth) ─────────────────────────
# (purpose, RomanEng word, token kind)
KW = [
    ("Print / Output", "dikhao", "PRINT"),
    ("If condition", "agar", "IF"),
    ("Else if", "warna agar", "ELIF"),
    ("Else", "warna", "ELSE"),
    ("Loop (while-style)", "jab_tak", "WHILE"),
    ("Loop (for-style)", "ginti", "FOR"),
    ("User input", "batao", "INPUT"),
    ("Function definition", "kaam", "FUNC"),
    ("Return", "wapis", "RETURN"),
    ("Break", "roko", "BREAK"),
    ("Continue", "agla", "CONTINUE"),
    ("Boolean true", "sach", "TRUE"),
    ("Boolean false", "jhoot", "FALSE"),
    ("Null / None", "khali", "NONE"),
]
# (purpose, RomanEng word, internal type)
TY = [
    ("String", "alfaaz", "str"),
    ("Integer", "adad", "int"),
    ("Float", "ashariya", "float"),
    ("Char", "nishan", "char"),
]
# (purpose, normal operator, RomanEng word)   <- blanks in the sheet were filled: minus / guna / barabar
OP = [
    ("Assignment", "=", "rakho"),
    ("Addition", "+", "jama"),
    ("Subtraction", "-", "minus"),
    ("Multiplication", "*", "guna"),
    ("Division", "/", "banto"),
    ("Greater than", ">", "se_zyada"),
    ("Less than", "<", "se_kam"),
    ("Equal comparison", "==", "barabar"),
    ("Not equal", "!=", "nahi_hai"),
    ("Logical And", "&&", "aur"),
    ("Logical OR", "||", "ya"),
]
KEYWORDS = {w: k for _, w, k in KW}
TYPES = {w: t for _, w, t in TY}
OPS = {w: sym for _, sym, w in OP}

BNF = """program  -> stmt*
stmt     -> declare | assign | print | input | if | while | for
          | func | return | roko | agla | call
declare  -> TYPE IDENT [ rakho expr ]      (jaise: adad x rakho 5)
assign   -> IDENT rakho expr
print    -> dikhao expr
input    -> batao IDENT
if       -> agar expr block { warna agar expr block } [ warna block ]
while    -> jab_tak expr block
for      -> ginti (declare | assign) ; expr ; assign block
func     -> kaam IDENT ( [TYPE IDENT {, TYPE IDENT}] ) block
return   -> wapis [ expr ]
block    -> { stmt* }
call     -> IDENT ( [ expr {, expr} ] )
TYPE     -> alfaaz | adad | ashariya | nishan

expr precedence (low -> high):
  ya  <  aur  <  barabar nahi_hai  <  se_zyada se_kam  <  jama minus  <  guna banto
primary  -> INT | FLOAT | "string" | 'c' | sach | jhoot | khali
          | IDENT | call | ( expr )
comment  -> # ... end of line"""

SAMPLE = '''# RomanEng sample program
alfaaz naam rakho "Ali"
adad n rakho 5
adad fact rakho 1

kaam jor(adad a, adad b) {
    wapis a jama b
}

ginti adad i rakho 1 ; i se_kam n jama 1 ; i rakho i jama 1 {
    fact rakho fact guna i
}
dikhao naam
dikhao fact

agar fact se_zyada 100 {
    dikhao "bara number"
} warna agar fact barabar 100 {
    dikhao "barabar"
} warna {
    dikhao "chota number"
}

dikhao jor(n, 10)
'''


class CompileError(Exception):
    def __init__(self, phase, line, msg):
        self.phase, self.line, self.msg = phase, line, msg
        super().__init__(f"{phase} Error" + (f" (line {line})" if line else "") + f": {msg}")


# ───────────────────────── GENERATOR 1 : LEXICAL ANALYZER (independent) ─────────────────────────
TOKEN_RE = re.compile(r"""
    (?P<WS>[ \t\r]+) | (?P<NL>\n) | (?P<COMMENT>\#[^\n]*)
  | (?P<ELIF>warna[ \t]+agar\b)
  | (?P<FLOAT>\d+\.\d+) | (?P<INT>\d+)
  | (?P<STRING>"[^"\n]*") | (?P<CHAR>'[^'\n]')
  | (?P<WORD>[A-Za-z_]\w*)
  | (?P<PUNCT>[(){},;])
  | (?P<BAD>.)
""", re.X)


def lex(src):
    toks, line = [], 1
    for m in TOKEN_RE.finditer(src):
        k, v = m.lastgroup, m.group()
        if k == "NL":
            line += 1
        elif k in ("WS", "COMMENT"):
            pass
        elif k == "ELIF":
            toks.append(("ELIF", "warna agar", line))
        elif k == "WORD":
            if v in KEYWORDS:
                toks.append((KEYWORDS[v], v, line))
            elif v in TYPES:
                toks.append(("TYPE", v, line))
            elif v in OPS:
                toks.append(("OP", v, line))
            else:
                toks.append(("IDENT", v, line))
        elif k == "PUNCT":
            toks.append((v, v, line))
        elif k == "BAD":
            raise CompileError("Lexical", line, f"invalid character '{v}'")
        else:  # INT FLOAT STRING CHAR
            toks.append((k, v, line))
    return toks


def category(kind):
    if kind in KEYWORDS.values():
        return "Keyword"
    return {"TYPE": "Datatype", "OP": "Operator", "IDENT": "Identifier", "INT": "Literal",
            "FLOAT": "Literal", "STRING": "Literal", "CHAR": "Literal"}.get(kind, "Punctuation")


# ───────────────────────── GENERATOR 2 : SYNTAX ANALYZER (needs tokens) ─────────────────────────
class N:
    """AST node"""
    def __init__(s, kind, line, **a):
        s.kind, s.line, s.a = kind, line, a

    def __getattr__(s, k):
        try:
            return s.__dict__["a"][k]
        except KeyError:
            raise AttributeError(k)


LEVELS = [["ya"], ["aur"], ["barabar", "nahi_hai"], ["se_zyada", "se_kam"], ["jama", "minus"], ["guna", "banto"]]


class Parser:
    def __init__(s, toks):
        s.t, s.i = toks, 0

    def peek(s):
        if s.i < len(s.t):
            return s.t[s.i]
        return ("EOF", "end of file", s.t[-1][2] if s.t else 1)

    def nxt(s):
        t = s.peek()
        s.i += 1
        return t

    def eat(s, k, what=None):
        t = s.peek()
        if t[0] != k:
            raise CompileError("Syntax", t[2], f"'{what or k}' expected, found '{t[1]}'")
        s.i += 1
        return t

    def program(s):
        body = []
        while s.peek()[0] != "EOF":
            body.append(s.stmt())
        return N("Program", 1, body=body)

    def block(s):
        s.eat("{")
        b = []
        while s.peek()[0] not in ("}", "EOF"):
            b.append(s.stmt())
        s.eat("}")
        return b

    def stmt(s):
        k, v, l = s.peek()
        if k == "TYPE":
            ty = s.nxt()[1]
            name = s.eat("IDENT", "variable name")[1]
            init = None
            if s.peek()[:2] == ("OP", "rakho"):
                s.nxt()
                init = s.expr()
            return N("Declare", l, type=TYPES[ty], name=name, init=init)
        if k == "PRINT":
            s.nxt()
            return N("Print", l, value=s.expr())
        if k == "INPUT":
            s.nxt()
            return N("Input", l, name=s.eat("IDENT", "variable name")[1])
        if k == "IF":
            s.nxt()
            br = []
            cond = s.expr()
            br.append(N("Branch", l, cond=cond, body=s.block()))
            while s.peek()[0] == "ELIF":
                bl = s.nxt()[2]
                cond = s.expr()
                br.append(N("Branch", bl, cond=cond, body=s.block()))
            els = []
            if s.peek()[0] == "ELSE":
                s.nxt()
                els = s.block()
            return N("If", l, branches=br, orelse=els)
        if k == "WHILE":
            s.nxt()
            cond = s.expr()
            return N("While", l, cond=cond, body=s.block())
        if k == "FOR":
            s.nxt()
            init = s.stmt()
            s.eat(";")
            cond = s.expr()
            s.eat(";")
            upd = s.stmt()
            return N("For", l, init=init, cond=cond, update=upd, body=s.block())
        if k == "FUNC":
            s.nxt()
            name = s.eat("IDENT", "function name")[1]
            s.eat("(")
            params = []
            if s.peek()[0] != ")":
                while True:
                    ty = s.eat("TYPE", "datatype")
                    pn = s.eat("IDENT", "parameter name")
                    params.append(N("Param", pn[2], type=TYPES[ty[1]], name=pn[1]))
                    if s.peek()[0] != ",":
                        break
                    s.nxt()
            s.eat(")")
            return N("Func", l, name=name, params=params, body=s.block())
        if k == "RETURN":
            s.nxt()
            nt = s.peek()
            val = None
            if nt[2] == l and nt[0] in ("INT", "FLOAT", "STRING", "CHAR", "IDENT", "TRUE", "FALSE", "NONE", "("):
                val = s.expr()
            return N("Return", l, value=val)
        if k == "BREAK":
            s.nxt()
            return N("Break", l)
        if k == "CONTINUE":
            s.nxt()
            return N("Continue", l)
        if k == "IDENT":
            nk = s.t[s.i + 1] if s.i + 1 < len(s.t) else ("EOF", "", l)
            if nk[:2] == ("OP", "rakho"):
                s.nxt()
                s.nxt()
                return N("Assign", l, name=v, value=s.expr())
            if nk[0] == "(":
                return N("ExprStmt", l, expr=s.expr())
            if v == "banao":
                raise CompileError("Syntax", l, "'banao' is not part of the language. Declare variables with a datatype, e.g. adad x rakho 5")
            raise CompileError("Syntax", l, f"expected 'rakho' or '(' after '{v}', found '{nk[1]}'")
        raise CompileError("Syntax", l, f"unexpected '{v}'")

    def expr(s, lv=0):
        if lv == len(LEVELS):
            return s.primary()
        n = s.expr(lv + 1)
        while s.peek()[0] == "OP" and s.peek()[1] in LEVELS[lv]:
            _, op, l = s.nxt()
            n = N("BinOp", l, op=op, sym=OPS[op], left=n, right=s.expr(lv + 1))
        return n

    def primary(s):
        k, v, l = s.nxt()
        if k == "INT":
            return N("Literal", l, type="int", value=int(v))
        if k == "FLOAT":
            return N("Literal", l, type="float", value=float(v))
        if k == "STRING":
            return N("Literal", l, type="str", value=v[1:-1])
        if k == "CHAR":
            return N("Literal", l, type="char", value=v[1:-1])
        if k == "TRUE":
            return N("Literal", l, type="bool", value=True)
        if k == "FALSE":
            return N("Literal", l, type="bool", value=False)
        if k == "NONE":
            return N("Literal", l, type="none")
        if k == "IDENT":
            if s.peek()[0] == "(":
                s.nxt()
                args = []
                if s.peek()[0] != ")":
                    args.append(s.expr())
                    while s.peek()[0] == ",":
                        s.nxt()
                        args.append(s.expr())
                s.eat(")")
                return N("Call", l, name=v, args=args)
            return N("Var", l, name=v)
        if k == "(":
            e = s.expr()
            s.eat(")")
            return e
        raise CompileError("Syntax", l, f"expression expected, found '{v}'")


def parse(toks):
    return Parser(toks).program()


def tree(n, d=0):
    """Convert the AST into a text tree"""
    pad = "    " * d
    if isinstance(n, list):
        out = []
        for x in n:
            out += tree(x, d)
        return out
    sc = ", ".join(f"{k}={v!r}" for k, v in n.a.items()
                   if isinstance(v, (str, int, float, bool)))
    out = [f"{pad}{'└─ ' if d else ''}{n.kind}" + (f"  [{sc}]" if sc else "")]
    for k, v in n.a.items():
        if isinstance(v, N) or (isinstance(v, list) and v):
            out.append(f"{pad}   {k}:")
            out += tree(v, d + 1)
    return out


# ───────────────────────── GENERATOR 3 : SEMANTIC ANALYZER (needs AST) ─────────────────────────
NUM = {"int", "float"}


def compat(t, v):
    return t == v or "any" in (t, v) or v == "none" or (t == "float" and v == "int")


class Semantic:
    def __init__(s):
        s.scopes, s.rows, s.errs, s.funcs = [{}], [], [], {}
        s.loop = s.infunc = 0

    def err(s, l, m):
        s.errs.append(f"Line {l}: {m}")

    def declare(s, name, ty, kind, l):
        if name in s.scopes[-1]:
            s.err(l, f"'{name}' is already declared in this scope")
            return
        s.scopes[-1][name] = ty
        s.rows.append({"Name": name, "Type": ty, "Kind": kind,
                       "Scope": "global" if len(s.scopes) == 1 else f"local-{len(s.scopes) - 1}", "Line": l})

    def lookup(s, name):
        for sc in reversed(s.scopes):
            if name in sc:
                return sc[name]

    def block(s, body):
        s.scopes.append({})
        for x in body:
            s.st(x)
        s.scopes.pop()

    def cond(s, c, l):
        t = s.ex(c)
        if t not in ("bool", "any"):
            s.err(l, f"condition must be boolean (sach/jhoot), found {t}")

    def ex(s, n):
        k, l = n.kind, n.line
        if k == "Literal":
            return n.type
        if k == "Var":
            t = s.lookup(n.name)
            if t is None:
                s.err(l, f"'{n.name}' is not declared")
                return "any"
            return t
        if k == "Call":
            ats = [s.ex(a) for a in n.args]
            f = s.funcs.get(n.name)
            if f is None:
                s.err(l, f"function '{n.name}' is not defined")
            elif len(f) != len(ats):
                s.err(l, f"'{n.name}' expects {len(f)} argument(s), got {len(ats)}")
            else:
                for i, (p, a) in enumerate(zip(f, ats), 1):
                    if not compat(p, a):
                        s.err(l, f"argument {i} of '{n.name}' must be {p}, found {a}")
            return "any"
        a, b, op = s.ex(n.left), s.ex(n.right), n.sym
        if op in ("&&", "||"):
            if a not in ("bool", "any") or b not in ("bool", "any"):
                s.err(l, f"'{n.op}' works only on booleans, found {a} and {b}")
            return "bool"
        if op in ("==", "!="):
            if not (a == b or "any" in (a, b) or "none" in (a, b) or {a, b} <= NUM):
                s.err(l, f"'{n.op}': cannot compare {a} with {b}")
            return "bool"
        if op in (">", "<"):
            if not ({a, b} <= NUM | {"any"} or {a, b} <= {"str", "char", "any"}):
                s.err(l, f"'{n.op}': cannot compare {a} with {b}")
            return "bool"
        if "any" in (a, b):
            return "any"
        if op == "+" and {a, b} <= {"str", "char"}:
            return "str"
        if {a, b} <= NUM:
            if op == "/" and a == b == "int":
                n.a["intdiv"] = True
            return "float" if "float" in (a, b) else "int"
        s.err(l, f"'{n.op}': invalid operands {a} and {b}")
        return "any"

    def st(s, n):
        k, l = n.kind, n.line
        if k == "Declare":
            vt = s.ex(n.init) if n.init is not None else None
            if vt is not None and not compat(n.type, vt):
                s.err(l, f"'{n.name}' is {n.type} but was assigned {vt}")
            s.declare(n.name, n.type, "variable", l)
        elif k == "Assign":
            t = s.lookup(n.name)
            vt = s.ex(n.value)
            if t is None:
                s.err(l, f"'{n.name}' is not declared")
            elif t == "function":
                s.err(l, f"'{n.name}' is a function and cannot be assigned")
            elif not compat(t, vt):
                s.err(l, f"'{n.name}' is {t} but was assigned {vt}")
        elif k == "Print":
            s.ex(n.value)
        elif k == "Input":
            t = s.lookup(n.name)
            if t is None:
                s.err(l, f"'{n.name}' is not declared")
            else:
                n.a["vtype"] = t
        elif k == "If":
            for b in n.branches:
                s.cond(b.cond, b.line)
                s.block(b.body)
            s.block(n.orelse)
        elif k == "While":
            s.cond(n.cond, l)
            s.loop += 1
            s.block(n.body)
            s.loop -= 1
        elif k == "For":
            s.scopes.append({})
            s.st(n.init)
            s.cond(n.cond, l)
            s.st(n.update)
            s.loop += 1
            s.block(n.body)
            s.loop -= 1
            s.scopes.pop()
        elif k == "Func":
            if n.name in s.funcs:
                s.err(l, f"function '{n.name}' is already defined")
            s.funcs[n.name] = [p.type for p in n.params]
            s.declare(n.name, "function", "function", l)
            s.scopes.append({})
            for p in n.params:
                s.declare(p.name, p.type, "param", p.line)
            sl, s.loop = s.loop, 0
            s.infunc += 1
            for x in n.body:
                s.st(x)
            s.infunc -= 1
            s.loop = sl
            s.scopes.pop()
        elif k == "Return":
            if not s.infunc:
                s.err(l, "'wapis' can only be used inside a function")
            if n.value is not None:
                s.ex(n.value)
        elif k in ("Break", "Continue"):
            if not s.loop:
                s.err(l, f"'{'roko' if k == 'Break' else 'agla'}' can only be used inside a loop")
        elif k == "ExprStmt":
            s.ex(n.expr)


def analyze(ast):
    sm = Semantic()
    for x in ast.body:
        sm.st(x)
    return sm.rows, sm.errs


# ───────────────────────── GENERATOR 4 : INTERMEDIATE CODE (needs checked AST) ─────────────────────────
DEFAULT = {"int": "0", "float": "0.0", "str": '""', "char": "''"}


def lit(n):
    v = n.a.get("value")
    return {"str": f'"{v}"', "char": f"'{v}'", "bool": "true" if v else "false", "none": "null"}.get(n.type, str(v))


class ICG:
    """Three-address code"""
    def __init__(s):
        s.c, s.nt, s.nl, s.loops = [], 0, 0, []

    def t(s):
        s.nt += 1
        return f"t{s.nt}"

    def L(s):
        s.nl += 1
        return f"L{s.nl}"

    def e(s, x):
        s.c.append("    " + x)

    def lab(s, l):
        s.c.append(f"{l}:")

    def ex(s, n):
        k = n.kind
        if k == "Literal":
            return lit(n)
        if k == "Var":
            return n.name
        if k == "Call":
            args = [s.ex(a) for a in n.args]
            for a in args:
                s.e(f"param {a}")
            t = s.t()
            s.e(f"{t} = call {n.name}, {len(args)}")
            return t
        a, b = s.ex(n.left), s.ex(n.right)
        t = s.t()
        s.e(f"{t} = {a} {n.sym} {b}")
        return t

    def st(s, n):
        k = n.kind
        if k == "Declare":
            s.e(f"{n.name} = {s.ex(n.init) if n.init is not None else DEFAULT[n.type]}")
        elif k == "Assign":
            s.e(f"{n.name} = {s.ex(n.value)}")
        elif k == "Print":
            s.e(f"param {s.ex(n.value)}")
            s.e("call print, 1")
        elif k == "Input":
            s.e(f"read {n.name}")
        elif k == "If":
            end = s.L()
            for b in n.branches:
                c = s.ex(b.cond)
                nx = s.L()
                s.e(f"ifFalse {c} goto {nx}")
                for x in b.body:
                    s.st(x)
                s.e(f"goto {end}")
                s.lab(nx)
            for x in n.orelse:
                s.st(x)
            s.lab(end)
        elif k == "While":
            a, z = s.L(), s.L()
            s.lab(a)
            s.e(f"ifFalse {s.ex(n.cond)} goto {z}")
            s.loops.append((a, z))
            for x in n.body:
                s.st(x)
            s.loops.pop()
            s.e(f"goto {a}")
            s.lab(z)
        elif k == "For":
            s.st(n.init)
            a, cont, z = s.L(), s.L(), s.L()
            s.lab(a)
            s.e(f"ifFalse {s.ex(n.cond)} goto {z}")
            s.loops.append((cont, z))
            for x in n.body:
                s.st(x)
            s.loops.pop()
            s.lab(cont)
            s.st(n.update)
            s.e(f"goto {a}")
            s.lab(z)
        elif k == "Func":
            s.c.append(f"func {n.name}({', '.join(p.name for p in n.params)}):")
            for x in n.body:
                s.st(x)
            s.c.append("endfunc")
        elif k == "Return":
            s.e("return" + (f" {s.ex(n.value)}" if n.value is not None else ""))
        elif k == "Break":
            s.e(f"goto {s.loops[-1][1]}")
        elif k == "Continue":
            s.e(f"goto {s.loops[-1][0]}")
        elif k == "ExprStmt":
            s.ex(n.expr)


def gen_icg(ast):
    g = ICG()
    for x in ast.body:
        g.st(x)
    return "\n".join(g.c)


# ───────────────────────── FINAL OUTPUT : AST -> Python -> run ─────────────────────────
class PyGen:
    def __init__(s):
        s.c, s.d, s.upd = [], 0, []

    def w(s, x):
        s.c.append("    " * s.d + x)

    def body(s, b):
        s.d += 1
        n = len(s.c)
        for x in b:
            s.st(x)
        if len(s.c) == n:
            s.w("pass")
        s.d -= 1

    def ex(s, n):
        k = n.kind
        if k == "Literal":
            return "None" if n.type == "none" else repr(n.value)
        if k == "Var":
            return n.name
        if k == "Call":
            return f"{n.name}({', '.join(s.ex(a) for a in n.args)})"
        op = {"&&": "and", "||": "or", "/": "//" if n.a.get("intdiv") else "/"}.get(n.sym, n.sym)
        return f"({s.ex(n.left)} {op} {s.ex(n.right)})"

    def st(s, n):
        k = n.kind
        if k == "Declare":
            s.w(f"{n.name} = {s.ex(n.init) if n.init is not None else DEFAULT[n.type]}")
        elif k == "Assign":
            s.w(f"{n.name} = {s.ex(n.value)}")
        elif k == "Print":
            s.w(f"print(_show({s.ex(n.value)}))")
        elif k == "Input":
            s.w(f"{n.name} = _read({n.a.get('vtype', 'str')!r})")
        elif k == "If":
            for i, b in enumerate(n.branches):
                s.w(f"{'if' if i == 0 else 'elif'} {s.ex(b.cond)}:")
                s.body(b.body)
            if n.orelse:
                s.w("else:")
                s.body(n.orelse)
        elif k == "While":
            s.w(f"while {s.ex(n.cond)}:")
            s.d += 1
            s.w("_tick()")
            s.d -= 1
            s.upd.append(None)
            s.body(n.body)
            s.upd.pop()
        elif k == "For":
            s.st(n.init)
            s.w(f"while {s.ex(n.cond)}:")
            s.d += 1
            s.w("_tick()")
            s.upd.append(n.update)
            for x in n.body:
                s.st(x)
            s.upd.pop()
            s.st(n.update)
            s.d -= 1
        elif k == "Func":
            s.w(f"def {n.name}({', '.join(p.name for p in n.params)}):")
            s.body(n.body)
        elif k == "Return":
            s.w("return" + (f" {s.ex(n.value)}" if n.value is not None else ""))
        elif k == "Break":
            s.w("break")
        elif k == "Continue":
            if s.upd and s.upd[-1] is not None:
                s.st(s.upd[-1])
            s.w("continue")
        elif k == "ExprStmt":
            s.w(s.ex(n.expr))


def to_python(ast):
    g = PyGen()
    for x in ast.body:
        g.st(x)
    return "\n".join(g.c)


def run_python(code, inputs):
    it = iter(inputs)
    ticks = [0]

    def _read(t):
        try:
            v = next(it)
        except StopIteration:
            raise CompileError("Runtime", 0, "Not enough input values for 'batao'. Add one value per line in the Input values box.")
        try:
            if t == "int":
                return int(v.strip())
            if t == "float":
                return float(v.strip())
            return v[:1] if t == "char" else v
        except ValueError:
            raise CompileError("Runtime", 0, f"cannot convert '{v}' to {t}")

    def _tick():
        ticks[0] += 1
        if ticks[0] > 200000:
            raise CompileError("Runtime", 0, "Possible infinite loop (limit of 200000 iterations reached)")

    def _show(v):
        return "sach" if v is True else "jhoot" if v is False else "khali" if v is None else v

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, {"_read": _read, "_tick": _tick, "_show": _show})
    except CompileError as e:
        return buf.getvalue(), str(e)
    except Exception as e:
        return buf.getvalue(), f"Runtime Error: {type(e).__name__}: {e}"
    return buf.getvalue(), None


# ───────────────────────── PHASE WRAPPERS (JSON-friendly, used by the Flask backend) ─────────────────────────
PHASE_INFO = [
    {"key": "lexical", "num": 1, "title": "Lexical Analyzer", "short": "Splits code into tokens",
     "input": "Source code", "output": "Tokens",
     "dep": "First phase of the pipeline. It only needs the source code.",
     "desc": "Reads the source code and groups characters into meaningful units called tokens.",
     "funcs": ["Recognizes keywords, data types, operators, identifiers, numbers, strings and characters",
               "Ignores spaces, new lines and # comments",
               "Classifies every token (Keyword, Datatype, Operator, Identifier, Literal, Punctuation)",
               "Reports invalid characters with their line number"]},
    {"key": "syntax", "num": 2, "title": "Syntax Analyzer", "short": "Builds the parse tree",
     "input": "Tokens", "output": "Parse tree (AST)",
     "dep": "Receives the tokens produced by the Lexical Analyzer.",
     "desc": "Checks that the tokens follow the grammar rules and builds a parse tree.",
     "funcs": ["Parses statements: declarations, agar / warna, jab_tak, ginti, kaam, wapis",
               "Parses expressions using operator precedence",
               "Builds the abstract syntax tree (AST)",
               "Reports syntax errors with their line number"]},
    {"key": "semantic", "num": 3, "title": "Semantic Analyzer", "short": "Checks types and scopes",
     "input": "Parse tree (AST)", "output": "Symbol table",
     "dep": "Receives the AST produced by the Syntax Analyzer.",
     "desc": "Checks that the program makes sense: types, declarations and scopes.",
     "funcs": ["Type checking for adad, ashariya, alfaaz and nishan",
               "Builds the symbol table (name, type, kind, scope, line)",
               "Detects undeclared variables, duplicate declarations and wrong function calls",
               "Allows roko / agla only inside loops and wapis only inside functions"]},
    {"key": "icg", "num": 4, "title": "Intermediate Code Generator", "short": "Generates three-address code",
     "input": "Checked AST", "output": "Three-address code",
     "dep": "Receives the AST that passed the Semantic Analyzer.",
     "desc": "Translates the verified program into machine-independent three-address code.",
     "funcs": ["Creates temporaries (t1, t2 ...) and labels (L1, L2 ...)",
               "Turns agar / jab_tak / ginti into ifFalse ... goto jumps",
               "Turns function calls into param / call / return instructions"]},
]


def _r(status, data=None, error=None):
    return {"status": status, "data": data or {}, "error": error}


def _blocked(by):
    return _r("blocked", error=f"Blocked: {by} did not pass")


def p_lexical(src):
    try:
        toks = lex(src)
    except CompileError as e:
        return _r("error", error=str(e)), None
    rows = [{"n": i + 1, "lexeme": v, "token": k, "category": category(k), "line": l}
            for i, (k, v, l) in enumerate(toks)]
    return _r("ok", {"tokens": rows}), toks


def p_syntax(toks):
    try:
        ast = parse(toks)
    except CompileError as e:
        return _r("error", error=str(e)), None
    return _r("ok", {"tree": "\n".join(tree(ast)) or "(empty program)"}), ast


def p_semantic(ast):
    rows, errs = analyze(ast)
    res = _r("error" if errs else "ok", {"symbols": rows, "errors": errs},
             f"{len(errs)} semantic error(s)" if errs else None)
    return res, not errs


def p_icg(ast):
    try:
        return _r("ok", {"tac": gen_icg(ast) or "(empty)"})
    except IndexError:
        return _r("error", error="'roko' / 'agla' used outside a loop")


def compile_all(src, inputs=""):
    """DEPENDENT mode: Lexical -> Syntax -> Semantic -> ICG, each phase uses the previous phase's output."""
    ph = {}
    ph["lexical"], toks = p_lexical(src)
    ast, ok = None, False
    if toks is None:
        ph["syntax"] = _blocked("Lexical Analyzer")
    else:
        ph["syntax"], ast = p_syntax(toks)
    if ast is None:
        ph["semantic"] = _blocked("Syntax Analyzer")
    else:
        ph["semantic"], ok = p_semantic(ast)
    ph["icg"] = p_icg(ast) if ok else _blocked("Semantic Analyzer")
    run = None
    if ok:
        py = to_python(ast)
        out, err = run_python(py, inputs.splitlines())
        run = {"python": py, "output": out, "error": err}
    return {"phases": ph, "run": run}


def run_one(key, src):
    """INDEPENDENT mode: one phase on its own source code, ignoring the other phases."""
    res, toks = p_lexical(src)
    if key == "lexical":
        return res
    if toks is None:
        return _r("error", error="Tokenizing failed, so this phase cannot run. " + res["error"])
    res, ast = p_syntax(toks)
    if key == "syntax" or ast is None:
        return res
    if key == "semantic":
        return p_semantic(ast)[0]
    return p_icg(ast)
