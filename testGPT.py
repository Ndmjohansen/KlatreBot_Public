import argparse
from KlatreGPT import KlatreGPT

discordkey = None
openaikey = None


def inputargs():
    parser = argparse.ArgumentParser(
        description="Et script til at læse navngivne argumenter fra kommandolinjen.")

    # Tilføj de navngivne argumenter, du vil læse
    parser.add_argument("--discordkey", type=str, help="Discord key")
    parser.add_argument("--openaikey", type=str, help="OpenAI key")

    args = parser.parse_args()

    # Gem de læste argumenter i variabler
    global discordkey
    discordkey = args.discordkey
    global openaikey
    openaikey = args.openaikey


inputargs()
KGPT = KlatreGPT(openaikey)


def hovedfunktion():
    while True:
        indtastning = input("Skriv en streng (eller 'q' for at afslutte): ")

        if indtastning.lower() == 'q':
            break  # Afslut loopet, hvis brugeren indtaster 'q'

        response_msg = KGPT.prompt_gpt(None, indtastning)
        print("gpt siger: " + response_msg)


if __name__ == "__main__":
    hovedfunktion()
