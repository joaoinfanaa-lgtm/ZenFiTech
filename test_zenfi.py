# -*- coding: utf-8 -*-
"""Testes ponta a ponta do ZenFi: sobe o servidor de verdade e usa HTTP.

    python -m unittest discover -s tests -v
"""
import hashlib
import hmac
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_SECRET = "segredo-de-teste-meta"
STRIPE_WH = "whsec_teste"


def porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Mock(BaseHTTPRequestHandler):
    """Finge ser a Meta (envio de mensagens) e a Stripe (checkout)."""
    capturado = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        corpo = self.rfile.read(n).decode()
        Mock.capturado.append((self.path, corpo, self.headers.get("Authorization", "")))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"url": "https://checkout.exemplo/sessao", "messages": [{"id": "x"}]}).encode())


class Cliente:
    """Um 'aparelho': guarda o cookie de sessão."""
    def __init__(self, porta):
        self.porta, self.cookie = porta, ""

    def req(self, metodo, caminho, corpo=None, headers=None, bruto=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=20)
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        h.update(headers or {})
        dados = bruto if bruto is not None else (json.dumps(corpo).encode() if corpo is not None else None)
        c.request(metodo, caminho, body=dados, headers=h)
        r = c.getresponse()
        txt = r.read()
        sc = r.getheader("Set-Cookie")
        c.close()
        if sc:
            par = sc.split(";")[0]
            self.cookie = par if not par.endswith("=") else ""
        try:
            return r.status, json.loads(txt)
        except ValueError:
            return r.status, txt.decode()


def subir_servidor(extra_env):
    porta, pasta = porta_livre(), tempfile.mkdtemp()
    env = dict(os.environ, PORT=str(porta), DATA_DIR=pasta, ZENFI_DEV="1", TRUST_PROXY="0")
    env.update(extra_env)
    p = subprocess.Popen([sys.executable, os.path.join(RAIZ, "servidor_zenfi_whatsapp.py")], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return p, porta, pasta


def assinar_meta(corpo):
    return "sha256=" + hmac.new(APP_SECRET.encode(), corpo, hashlib.sha256).hexdigest()


class BaseTeste(unittest.TestCase):
    EXTRA = {}

    @classmethod
    def setUpClass(cls):
        cls.mock_porta = porta_livre()
        cls.mock = HTTPServer(("127.0.0.1", cls.mock_porta), Mock)
        threading.Thread(target=cls.mock.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % cls.mock_porta
        env = {"META_APP_SECRET": APP_SECRET, "META_VERIFY_TOKEN": "verifica-123",
               "WHATSAPP_TOKEN": "token-falso-teste", "WHATSAPP_PHONE_NUMBER_ID": "111222",
               "WHATSAPP_API_BASE": base, "WHATSAPP_NUMERO_PUBLICO": "5511900000000",
               "STRIPE_SECRET_KEY": "sk_test_falso", "STRIPE_PRICE_ID": "price_falso",
               "STRIPE_WEBHOOK_SECRET": STRIPE_WH, "STRIPE_API_BASE": base}
        env.update(cls.EXTRA)
        cls.proc, cls.porta, cls.pasta = subir_servidor(env)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.mock.shutdown()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def novo(self):
        return Cliente(self.porta)

    def cadastrar(self, nome="Maria", email=None, senha="senha123"):
        c = self.novo()
        email = email or "u%d@teste.com" % int(time.time() * 1e6)
        st, d = c.req("POST", "/api/cadastro", {"nome": nome, "email": email, "senha": senha})
        self.assertEqual(st, 200, d)
        return c, email, senha

    def webhook(self, c, de, texto, wamid=None, tipo="text"):
        msg = {"id": wamid or "wamid.%d" % int(time.time() * 1e6), "from": de, "type": tipo, "text": {"body": texto}}
        corpo = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [msg]}}]}]}).encode()
        st, _ = c.req("POST", "/webhook/whatsapp", bruto=corpo, headers={"X-Hub-Signature-256": assinar_meta(corpo)})
        return st

    def respostas_enviadas(self, a_partir=0, espera=1.5):
        fim = time.time() + espera
        while time.time() < fim:
            msgs = [json.loads(b)["text"]["body"] for p, b, _ in Mock.capturado if "/messages" in p and '"type": "text"' in b]
            if len(msgs) > a_partir:
                break
            time.sleep(0.05)
        return [json.loads(b) for p, b, _ in Mock.capturado if "/messages" in p][a_partir:]

    def vincular(self, c, telefone):
        st, d = c.req("POST", "/api/whatsapp/vinculo/codigo", {})
        self.assertEqual(st, 200, d)
        self.assertTrue(d["codigo"].startswith("ZEN-"))
        self.assertIn("wa.me/5511900000000", d["link"])
        self.assertEqual(self.webhook(c, telefone, d["codigo"]), 200)
        time.sleep(0.3)
        st, v = c.req("GET", "/api/whatsapp/vinculo")
        self.assertTrue(v["vinculado"], v)


class TestConta(BaseTeste):
    def test_cadastro_login_varios_aparelhos(self):
        a, email, senha = self.cadastrar()
        st, eu = a.req("GET", "/api/eu")
        self.assertEqual((st, eu["email"]), (200, email))
        b = self.novo()
        st, _ = b.req("POST", "/api/entrar", {"identificador": email, "senha": "errada!"})
        self.assertEqual(st, 401)
        st, d = b.req("POST", "/api/entrar", {"identificador": email, "senha": senha})
        self.assertEqual(st, 200)
        self.assertEqual(b.req("GET", "/api/eu")[0], 200)
        self.assertEqual(self.novo().req("GET", "/api/eu")[0], 401)   # sem sessão
        a.req("POST", "/api/sair", {})
        self.assertEqual(a.req("GET", "/api/eu")[0], 401)
        self.assertEqual(b.req("GET", "/api/eu")[0], 200)             # outro aparelho continua

    def test_validacoes_e_duplicidade(self):
        c = self.novo()
        self.assertEqual(c.req("POST", "/api/cadastro", {"nome": "A", "email": "x@y.com", "senha": "123456"})[0], 400)
        self.assertEqual(c.req("POST", "/api/cadastro", {"nome": "Ana", "email": "ruim", "senha": "123456"})[0], 400)
        self.assertEqual(c.req("POST", "/api/cadastro", {"nome": "Ana", "email": "ana@y.com", "senha": "123"})[0], 400)
        self.assertEqual(c.req("POST", "/api/cadastro", {"nome": "Ana", "email": "ana2@y.com", "senha": "123456", "documento": "11111111111"})[0], 400)
        self.assertEqual(c.req("POST", "/api/cadastro", {"nome": "Ana", "email": "ana3@y.com", "senha": "123456", "documento": "52998224725"})[0], 200)
        self.assertEqual(self.novo().req("POST", "/api/cadastro", {"nome": "Ana", "email": "ANA3@y.com", "senha": "123456"})[0], 409)

    def test_arquivos_do_app_instalavel(self):
        c = self.novo()
        st, man = c.req("GET", "/manifest.webmanifest")
        self.assertEqual(st, 200)
        self.assertEqual(man["display"], "standalone")
        self.assertTrue(any(i["purpose"] == "maskable" for i in man["icons"]))
        for caminho in ("/sw.js", "/icon-192.png", "/icon-512.png", "/icon-maskable.png", "/apple-touch-icon.png", "/"):
            conn = http.client.HTTPConnection("127.0.0.1", c.porta, timeout=10)
            conn.request("GET", caminho)
            r = conn.getresponse(); r.read()
            self.assertEqual(r.status, caminho and 200, caminho)
            self.assertIn("microphone=(self)", r.getheader("Permissions-Policy", ""))

    def test_senha_guardada_com_hash(self):
        self.cadastrar(email="hash@teste.com", senha="minha-senha-secreta")
        import sqlite3
        con = sqlite3.connect(os.path.join(self.pasta, "zenfi.db"))
        h = con.execute("SELECT senha_hash FROM usuarios WHERE email='hash@teste.com'").fetchone()[0]
        con.close()
        self.assertTrue(h.startswith("pbkdf2_sha256$"))
        self.assertNotIn("minha-senha-secreta", h)

    def test_bloqueio_apos_muitas_tentativas(self):
        _, email, _ = self.cadastrar()
        c = self.novo()
        codigos = [c.req("POST", "/api/entrar", {"identificador": email, "senha": "x" * 8})[0] for _ in range(6)]
        self.assertEqual(codigos[:5], [401] * 5)
        self.assertEqual(codigos[5], 429)

    def test_recuperar_senha(self):
        a, email, senha = self.cadastrar()
        st, d = self.novo().req("POST", "/api/senha/esqueci", {"email": email})
        self.assertEqual(st, 200)
        token = d["dev_link"].split("#redefinir=")[1]
        # e-mail inexistente recebe a mesma resposta (não revela contas)
        st2, d2 = self.novo().req("POST", "/api/senha/esqueci", {"email": "nao@existe.com"})
        self.assertEqual((st2, d2["mensagem"]), (200, d["mensagem"]))
        self.assertNotIn("dev_link", d2)
        self.assertEqual(self.novo().req("POST", "/api/senha/redefinir", {"token": "invalido", "senha": "novasenha1"})[0], 400)
        self.assertEqual(self.novo().req("POST", "/api/senha/redefinir", {"token": token, "senha": "novasenha1"})[0], 200)
        self.assertEqual(a.req("GET", "/api/eu")[0], 401)             # sessões antigas caem
        self.assertEqual(self.novo().req("POST", "/api/entrar", {"identificador": email, "senha": senha})[0], 401)
        self.assertEqual(self.novo().req("POST", "/api/entrar", {"identificador": email, "senha": "novasenha1"})[0], 200)
        self.assertEqual(self.novo().req("POST", "/api/senha/redefinir", {"token": token, "senha": "outra1234"})[0], 400)  # uso único


class TestNuvem(BaseTeste):
    MES = "contas-da-casa:2026-11"

    def test_sincroniza_entre_aparelhos_e_isola_usuarios(self):
        a, email, senha = self.cadastrar()
        doc = {"incomes": [{"id": "i1", "desc": "Salário", "amount": 500000}], "bills": [], "planned": []}
        st, r = a.req("POST", "/api/sync", {"itens": [{"k": self.MES, "v": json.dumps(doc), "bs": 0},
                                                      {"k": "organiza:profile", "v": json.dumps({"name": "Maria"}), "bs": 0}]})
        self.assertEqual(st, 200, r)
        self.assertEqual(len(r["aceitos"]), 2)
        b = self.novo()
        b.req("POST", "/api/entrar", {"identificador": email, "senha": senha})     # "outro celular"
        st, g = b.req("GET", "/api/sync?desde=0")
        chaves = {i["k"]: i for i in g["itens"]}
        self.assertEqual(json.loads(chaves[self.MES]["v"])["incomes"][0]["desc"], "Salário")
        self.assertIn("organiza:profile", chaves)
        # só o que mudou depois
        self.assertEqual(b.req("GET", "/api/sync?desde=%d" % g["seq"])[1]["itens"], [])
        # outro usuário não enxerga nada
        outro, _, _ = self.cadastrar(nome="Outro")
        self.assertEqual(outro.req("GET", "/api/sync?desde=0")[1]["itens"], [])
        # chaves locais do aparelho não sobem
        st, r = a.req("POST", "/api/sync", {"itens": [{"k": "organiza:pin", "v": "1234", "bs": 0}]})
        self.assertEqual(r["rejeitados"][0]["motivo"], "invalido")
        self.assertEqual(self.novo().req("POST", "/api/sync", {"itens": []})[0], 401)

    def test_dois_aparelhos_editando_o_mesmo_mes_nao_perdem_lancamentos(self):
        a, email, senha = self.cadastrar()
        base = {"incomes": [], "bills": [{"id": "b1", "desc": "Aluguel", "amount": 100000, "cat": "Moradia", "day": 5}], "planned": []}
        r = a.req("POST", "/api/sync", {"itens": [{"k": self.MES, "v": json.dumps(base), "bs": 0}]})[1]
        s0 = r["aceitos"][0]["s"]
        b = self.novo()
        b.req("POST", "/api/entrar", {"identificador": email, "senha": senha})
        # A adiciona "Mercado"; B (sem ver) adiciona "Luz" e apaga "Aluguel"
        va = json.loads(json.dumps(base)); va["bills"].append({"id": "b2", "desc": "Mercado", "amount": 20000, "cat": "Mercado", "day": 6})
        vb = {"incomes": [], "bills": [{"id": "b3", "desc": "Luz", "amount": 15000, "cat": "Contas e serviços", "day": 7}], "planned": []}
        a.req("POST", "/api/sync", {"itens": [{"k": self.MES, "v": json.dumps(va), "bs": s0}]})
        rb = b.req("POST", "/api/sync", {"itens": [{"k": self.MES, "v": json.dumps(vb), "bs": s0}]})[1]
        final = json.loads(rb["devolver"][0]["v"])
        ids = sorted(x["id"] for x in final["bills"])
        self.assertEqual(ids, ["b2", "b3"])           # Mercado (de A) + Luz (de B); Aluguel apagado por B

    def test_whatsapp_chega_no_aparelho_aberto(self):
        a, _, _ = self.cadastrar()
        self.vincular(a, "5511988887777")
        g = a.req("GET", "/api/sync?desde=0")[1]
        antes = g["seq"]
        self.assertEqual(self.webhook(a, "5511988887777", "Gastei R$ 35 no almoço"), 200)
        time.sleep(0.4)
        novo = a.req("GET", "/api/sync?desde=%d" % antes)[1]["itens"]
        mes = [i for i in novo if i["k"].startswith("contas-da-casa:")][0]
        bill = json.loads(mes["v"])["bills"][0]
        self.assertEqual((bill["desc"], bill["amount"], bill["cat"], bill["src"]), ("Almoço", 3500, "Alimentação", "whatsapp"))


class TestWhatsApp(BaseTeste):
    def test_verificacao_do_webhook_da_meta(self):
        c = self.novo()
        st, corpo = c.req("GET", "/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=verifica-123&hub.challenge=abc123")
        self.assertEqual((st, corpo), (200, "abc123"))
        self.assertEqual(c.req("GET", "/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=errado&hub.challenge=x")[0], 403)

    def test_assinatura_invalida_e_recusada(self):
        c = self.novo()
        corpo = b'{"object":"whatsapp_business_account","entry":[]}'
        self.assertEqual(c.req("POST", "/webhook/whatsapp", bruto=corpo, headers={"X-Hub-Signature-256": "sha256=00"})[0], 403)
        self.assertEqual(c.req("POST", "/webhook/whatsapp", bruto=corpo)[0], 403)

    def test_exemplos_do_pedido(self):
        c, _, _ = self.cadastrar()
        self.vincular(c, "5511977776666")
        casos = [("Gastei R$ 35 no almoço", "despesa", 3500, "Almoço", "Alimentação"),
                 ("Paguei R$ 120 de gasolina", "despesa", 12000, "Gasolina", "Transporte"),
                 ("Recebi R$ 2.500 de salário", "receita", 250000, "Salário", None),
                 ("Paguei R$ 90 de internet", "despesa", 9000, "Internet", "Internet fixa")]
        for texto, *_ in casos:
            self.assertEqual(self.webhook(c, "5511977776666", texto), 200)
        time.sleep(0.5)
        itens = c.req("GET", "/api/sync?desde=0")[1]["itens"]
        mes = json.loads([i for i in itens if i["k"] == "contas-da-casa:%s" % date.today().strftime("%Y-%m")][0]["v"])
        achados = {(b["desc"], b["amount"], b["cat"]) for b in mes["bills"]}
        self.assertEqual(achados, {("Almoço", 3500, "Alimentação"), ("Gasolina", 12000, "Transporte"), ("Internet", 9000, "Internet fixa")})
        self.assertEqual([(r["desc"], r["amount"]) for r in mes["incomes"]], [("Salário", 250000)])

    def test_confirmacao_e_duplicidade(self):
        c, _, _ = self.cadastrar()
        self.vincular(c, "5511966665555")
        n0 = len([1 for p, *_ in Mock.capturado if "/messages" in p])
        self.assertEqual(self.webhook(c, "5511966665555", "Paguei R$ 77,70 no mercado", wamid="wamid.A"), 200)
        env = self.respostas_enviadas(n0)
        self.assertEqual(len(env), 1)
        self.assertEqual(env[0]["to"], "5511966665555")
        self.assertIn("Despesa registrada", env[0]["text"]["body"])
        self.assertIn("R$ 77,70", env[0]["text"]["body"])
        # a Meta reenvia o mesmo webhook (mesmo wamid): não duplica nem responde de novo
        self.assertEqual(self.webhook(c, "5511966665555", "Paguei R$ 77,70 no mercado", wamid="wamid.A"), 200)
        # mensagem nova, mas igual à anterior em 2 min: avisa e não lança
        self.assertEqual(self.webhook(c, "5511966665555", "Paguei R$ 77,70 no mercado", wamid="wamid.B"), 200)
        env2 = self.respostas_enviadas(n0 + 1)
        self.assertIn("Não lancei de novo", env2[0]["text"]["body"])
        itens = c.req("GET", "/api/sync?desde=0")[1]["itens"]
        mes = json.loads([i for i in itens if i["k"].startswith("contas-da-casa:")][0]["v"])
        self.assertEqual(len([b for b in mes["bills"] if b["amount"] == 7770]), 1)

    def test_mensagem_nao_entendida_e_numero_desconhecido(self):
        c, _, _ = self.cadastrar()
        self.vincular(c, "5511955554444")
        n0 = len([1 for p, *_ in Mock.capturado if "/messages" in p])
        self.webhook(c, "5511955554444", "bom dia, tudo bem?")
        env = self.respostas_enviadas(n0)
        self.assertIn("ajuda", env[0]["text"]["body"])          # saudação: responde com exemplos, não com erro
        n0 += 1
        self.webhook(c, "5511955554444", "blablabla 12")
        env = self.respostas_enviadas(n0)
        self.assertIn("Não consegui entender", env[0]["text"]["body"])
        self.assertIn("gasto ou uma receita", env[0]["text"]["body"])
        n1 = len([1 for p, *_ in Mock.capturado if "/messages" in p])
        self.webhook(c, "5521900001111", "Gastei R$ 10 no lanche")
        env = self.respostas_enviadas(n1)
        self.assertIn("não está vinculado", env[0]["text"]["body"])


    def _corpo(self, n0):
        env = self.respostas_enviadas(n0)
        return env[0]["text"]["body"] if env else ""

    def _n(self):
        return len([1 for p, *_ in Mock.capturado if "/messages" in p])

    def test_varios_lancamentos_comandos_e_desfazer(self):
        c, _, _ = self.cadastrar()
        tel = "5511933332222"
        self.vincular(c, tel)
        mes = "contas-da-casa:%s" % date.today().strftime("%Y-%m")

        def doc():
            itens = c.req("GET", "/api/sync?desde=0")[1]["itens"]
            r = [i for i in itens if i["k"] == mes]
            return json.loads(r[-1]["v"]) if r else {"bills": [], "incomes": []}

        n = self._n()
        self.webhook(c, tel, "gastei 30 no lanche e 20 no uber")
        txt = self._corpo(n)
        self.assertIn("2 lançamentos registrados", txt)
        self.assertEqual(sorted(b["amount"] for b in doc()["bills"]), [2000, 3000])
        # atalho sem verbo
        n = self._n(); self.webhook(c, tel, "mercado 230"); self.assertIn("Despesa registrada", self._corpo(n))
        # saldo / resumo / extrato
        n = self._n(); self.webhook(c, tel, "saldo"); self.assertIn("-R$ 280,00", self._corpo(n))
        n = self._n(); self.webhook(c, tel, "resumo"); self.assertIn("Onde mais gastou", self._corpo(n))
        n = self._n(); self.webhook(c, tel, "extrato"); self.assertIn("Mercado", self._corpo(n))
        # desfazer remove só o último (o mercado) e some do app
        n = self._n(); self.webhook(c, tel, "desfazer"); self.assertIn("Desfeito", self._corpo(n))
        self.assertEqual(sorted(b["amount"] for b in doc()["bills"]), [2000, 3000])
        # depois de desfeito, repetir logo em seguida NÃO é duplicidade
        n = self._n(); self.webhook(c, tel, "mercado 230"); self.assertIn("Despesa registrada", self._corpo(n))
        # igual em 2 min: avisa; com "de novo" lança
        n = self._n(); self.webhook(c, tel, "mercado 230"); self.assertIn("Não lancei de novo", self._corpo(n))
        n = self._n(); self.webhook(c, tel, "mercado 230 de novo"); self.assertIn("Despesa registrada", self._corpo(n))
        # ajuda e reação (sem resposta)
        n = self._n(); self.webhook(c, tel, "ajuda"); self.assertIn("Comandos", self._corpo(n))
        n = self._n()
        msg = {"id": "wamid.reacao", "from": tel, "type": "reaction", "reaction": {"emoji": "👍"}}
        corpo = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [msg]}}]}]}).encode()
        c.req("POST", "/webhook/whatsapp", bruto=corpo, headers={"X-Hub-Signature-256": assinar_meta(corpo)})
        time.sleep(0.4)
        self.assertEqual(self._n(), n)

    def test_respostas_chegam_na_ordem(self):
        c, _, _ = self.cadastrar()
        tel = "5511922221111"
        self.vincular(c, tel)
        n = self._n()
        for i in range(1, 5):
            self.webhook(c, tel, "gastei %d no cafe" % (i * 7))
        self.respostas_enviadas(n + 3, espera=3)
        corpos = [json.loads(b)["text"]["body"] for p, b, _ in Mock.capturado if "/messages" in p][n:]
        self.assertEqual([("R$ %d,00" % (i * 7)) in t for i, t in zip(range(1, 5), corpos)], [True] * 4)

    def test_numero_so_vincula_a_uma_conta(self):
        a, _, _ = self.cadastrar()
        b, _, _ = self.cadastrar()
        self.vincular(a, "5511944443333")
        st, d = b.req("POST", "/api/whatsapp/vinculo/codigo", {})
        n0 = len([1 for p, *_ in Mock.capturado if "/messages" in p])
        self.webhook(b, "5511944443333", d["codigo"])
        self.assertIn("já está vinculado", self.respostas_enviadas(n0)[0]["text"]["body"])
        self.assertFalse(b.req("GET", "/api/whatsapp/vinculo")[1]["vinculado"])


class TestPlanos(BaseTeste):
    EXTRA = {"TRIAL_DIAS": "0", "LIMITE_GRATIS_LANCAMENTOS": "3"}

    def evento(self, tipo, obj, eid=None):
        corpo = json.dumps({"id": eid or "evt_%d" % int(time.time() * 1e6), "type": tipo, "data": {"object": obj}}).encode()
        t = str(int(time.time()))
        sig = hmac.new(STRIPE_WH.encode(), t.encode() + b"." + corpo, hashlib.sha256).hexdigest()
        return corpo, {"Stripe-Signature": "t=%s,v1=%s" % (t, sig)}

    def test_gratis_tem_limites_e_pro_libera(self):
        c, _, _ = self.cadastrar()
        eu = c.req("GET", "/api/eu")[1]
        self.assertEqual(eu["plano"]["plano"], "gratis")
        self.assertEqual(eu["plano"]["preco"], "R$ 44,90")
        # WhatsApp é do Pro
        st, d = c.req("POST", "/api/whatsapp/vinculo/codigo", {})
        self.assertEqual(st, 402)
        self.assertTrue(d["upgrade"])
        # limite de lançamentos por mês
        mes = "contas-da-casa:2026-11"
        ok = {"incomes": [], "bills": [{"id": "x%d" % i, "desc": "c", "amount": 100, "cat": "Outros", "day": 1} for i in range(3)], "planned": []}
        self.assertEqual(c.req("POST", "/api/sync", {"itens": [{"k": mes, "v": json.dumps(ok), "bs": 0}]})[1]["aceitos"][0]["k"], mes)
        mais = json.loads(json.dumps(ok)); mais["bills"].append({"id": "x9", "desc": "c", "amount": 100, "cat": "Outros", "day": 2})
        r = c.req("POST", "/api/sync", {"itens": [{"k": mes, "v": json.dumps(mais), "bs": 1}]})[1]
        self.assertEqual(r["rejeitados"][0]["motivo"], "limite")
        self.assertEqual(len(json.loads(r["devolver"][0]["v"])["bills"]), 3)   # servidor devolve o estado válido
        # checkout (Stripe simulada)
        n0 = len(Mock.capturado)
        st, ck = c.req("POST", "/api/assinatura/checkout", {})
        self.assertEqual((st, ck["url"]), (200, "https://checkout.exemplo/sessao"))
        caminho, corpo, auth = Mock.capturado[n0]
        self.assertEqual(caminho, "/v1/checkout/sessions")
        self.assertIn("mode=subscription", corpo)
        self.assertIn("price_falso", corpo)
        self.assertEqual(auth, "Bearer sk_test_falso")
        # pagamento aprovado -> webhook assinado
        uid = eu["id"]
        corpo, h = self.evento("checkout.session.completed", {"client_reference_id": str(uid), "customer": "cus_1", "subscription": "sub_1"}, "evt_ok")
        self.assertEqual(self.novo().req("POST", "/webhook/stripe", bruto=corpo, headers=h)[0], 200)
        self.assertEqual(self.novo().req("POST", "/webhook/stripe", bruto=corpo, headers=h)[0], 200)  # reenvio idempotente
        eu = c.req("GET", "/api/eu")[1]
        self.assertEqual((eu["plano"]["plano"], eu["plano"]["whatsapp"], eu["plano"]["limite_lancamentos_mes"]), ("pro", True, None))
        self.assertEqual(c.req("POST", "/api/whatsapp/vinculo/codigo", {})[0], 200)
        self.assertEqual(c.req("POST", "/api/sync", {"itens": [{"k": mes, "v": json.dumps(mais), "bs": 1}]})[1]["rejeitados"], [])
        # assinatura cancelada volta ao gratuito
        corpo, h = self.evento("customer.subscription.deleted", {"customer": "cus_1"})
        self.novo().req("POST", "/webhook/stripe", bruto=corpo, headers=h)
        self.assertEqual(c.req("GET", "/api/eu")[1]["plano"]["plano"], "gratis")

    def test_webhook_de_pagamento_exige_assinatura(self):
        corpo = json.dumps({"id": "evt_falso", "type": "checkout.session.completed", "data": {"object": {"client_reference_id": "1"}}}).encode()
        self.assertEqual(self.novo().req("POST", "/webhook/stripe", bruto=corpo, headers={"Stripe-Signature": "t=1,v1=abc"})[0], 400)
        self.assertEqual(self.novo().req("POST", "/webhook/stripe", bruto=corpo)[0], 400)


class TestTeste7Dias(BaseTeste):
    def test_conta_nova_ganha_7_dias_de_pro(self):
        c, _, _ = self.cadastrar()
        p = c.req("GET", "/api/eu")[1]["plano"]
        self.assertEqual((p["plano"], p["teste"], p["whatsapp"]), ("pro", True, True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
