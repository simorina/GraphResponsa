import sys
from pathlib import Path
sys.path.insert(0, 'src')
from agente.agente import rispondi

domanda = "Cosa stabilisce il Libro Primo degli Statuti del 1600 di San Marino riguardo all'Arringo Generale e alla Rubrica I?"
print("DOMANDA TEST:", domanda)
print("=" * 70)

for evento in rispondi(domanda):
    t = evento.get("tipo")
    if t == "strumento":
        print(f"\n[TOOL USATO] -> {evento.get('nome')}({evento.get('argomenti')})")
    elif t == "testo":
        print(evento.get("testo", ""), end="", flush=True)

print("\n" + "=" * 70)
