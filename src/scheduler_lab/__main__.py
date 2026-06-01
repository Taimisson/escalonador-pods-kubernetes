# permite rodar o pacote com "python -m scheduler_lab".
# é assim que os scripts .ps1 chamam o CLI sem precisar instalar o entrypoint
from scheduler_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
