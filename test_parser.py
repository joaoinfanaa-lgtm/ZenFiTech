# -*- coding: utf-8 -*-
"""Testes do entendimento de mensagens (sem servidor): python -m unittest discover -s tests -v"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import zenfi_parser as z  # noqa: E402

HOJE = date(2026, 11, 3)


def um(texto):
    r = z.interpretar_varios(texto, HOJE)
    assert len(r) == 1, (texto, r)
    r = r[0]
    return r["tipo"], r["centavos"], r["descricao"], r["categoria"], str(r["data"])


class TestParser(unittest.TestCase):
    def test_exemplos_basicos(self):
        self.assertEqual(um("Gastei R$ 35 no almoço"), ("despesa", 3500, "Almoço", "Alimentação", "2026-11-03"))
        self.assertEqual(um("Recebi R$ 2.500 de salário"), ("receita", 250000, "Salário", "", "2026-11-03"))
        self.assertEqual(um("Gastei R$35,00 no almoço.")[1], 3500)

    def test_numero_nao_vira_categoria(self):
        self.assertEqual(um("paguei 99 na netflix")[3], "Lazer")          # antes caía em Transporte (\b99\b)
        self.assertEqual(um("paguei 99 no 99 pop")[3], "Transporte")

    def test_valores(self):
        for txt, c in [("paguei 1,5 mil de condomínio", 150000), ("recebi 5k de bônus", 500000), ("paguei 1.5k", 150000),
                       ("gastei 1.234 de carro", 123400), ("gastei vinte reais no almoço", 2000),
                       ("gastei cinquenta e cinco reais", 5500), ("recebi 2 mil e quinhentos", 250000),
                       ("gastei dois mil e quinhentos no aluguel", 250000), ("gastei 10 reais e 50 centavos no pão", 1050)]:
            self.assertEqual(um(txt)[1], c, txt)

    def test_parcela_nao_e_data_nem_valor(self):
        r = um("paguei a parcela 3/10 do carro de 450")
        self.assertEqual((r[1], r[4]), (45000, "2026-11-03"))
        self.assertEqual(um("paguei a parcela 3 de 10 do carro de 450")[1], 45000)

    def test_datas(self):
        self.assertEqual(um("gastei 50 no uber ontem")[4], "2026-11-02")
        self.assertEqual(um("paguei 80 dia 5 de luz")[4], "2026-10-05")
        self.assertEqual(um("gastei 45 em 28/10 na farmácia")[4], "2026-10-28")
        self.assertEqual(um("gastei 50 no uber na sexta")[4], "2026-10-30")

    def test_sem_verbo_e_sinais(self):
        self.assertEqual(um("almoço 35")[:2], ("despesa", 3500))
        self.assertEqual(um("salário 3000")[:2], ("receita", 300000))
        self.assertEqual(um("+500 pix")[:2], ("receita", 50000))
        self.assertEqual(um("-30 café")[:2], ("despesa", 3000))

    def test_verbos_novos(self):
        self.assertEqual(um("fiz um pix de 200 pro joão")[0], "despesa")
        self.assertEqual(um("me devolveram 40")[0], "receita")
        self.assertEqual(um("estorno de 50")[0], "receita")

    def test_varios_lancamentos(self):
        r = z.interpretar_varios("ontem gastei 60 no jantar e 20 no uber", HOJE)
        self.assertEqual([(x["centavos"], x["categoria"], str(x["data"])) for x in r],
                         [(6000, "Alimentação", "2026-11-02"), (2000, "Transporte", "2026-11-02")])
        r = z.interpretar_varios("gastei 35 no almoço e 15 no café\nrecebi 200 de freela", HOJE)
        self.assertEqual([x["tipo"] for x in r], ["despesa", "despesa", "receita"])
        self.assertEqual(len(z.interpretar_varios("gastei 30 no lanche e café", HOJE)), 1)

    def test_nao_entende(self):
        for txt in ["oi", "gastei 0 no almoço", "comprei um café", "gastei 10 dólares", "gastei 3x de 50", "blablabla 12"]:
            self.assertEqual(z.interpretar_varios(txt, HOJE), [], txt)
        self.assertEqual(z.motivo_falha("gastei 10 dólares"), "moeda")
        self.assertEqual(z.motivo_falha("gastei 3x de 50"), "parcelado")
        self.assertEqual(z.motivo_falha("gastei no mercado"), "sem_valor")
        self.assertEqual(z.motivo_falha("blablabla 12"), "sem_tipo")

    def test_comandos(self):
        casos = {"saldo": "saldo", "Resumo do mês passado": "resumo", "oi": "saudacao", "bom dia, tudo bem?": "saudacao",
                 "desfazer": "desfazer", "ajuda": "ajuda", "?": "ajuda", "valeu!": "agradecimento", "ok": "ciente",
                 "extrato": "extrato", "quanto gastei esse mês": "resumo", "quanto sobrou": "saldo"}
        for txt, nome in casos.items():
            self.assertEqual((z.comando(txt) or (None,))[0], nome, txt)
        self.assertEqual(z.comando("resumo do mês passado")[1], {"mes": "passado"})
        # perigosos: nunca viram comando
        for txt in ["apagar tudo", "cancelar plano", "salário 3000", "gastei 10 no saldo"]:
            self.assertIsNone(z.comando(txt), txt)


if __name__ == "__main__":
    unittest.main()
