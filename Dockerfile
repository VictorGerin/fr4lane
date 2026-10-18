# Ambiente Linux de referência do pcbflow: Yosys, Icarus Verilog, KiCad (DRC)
# e Chromium (testes da página do editor). Roda a suíte de testes:
#
#   docker build -t pcbflow .
#   docker run --rm pcbflow                               # python -m pytest
#   docker run --rm -v "$PWD/meu_projeto:/proj" -w /proj pcbflow pcbflow --top meu_top
#
# WITH_KICAD=0 deixa o KiCad de fora (imagem bem menor; o DRC fica pulado).
FROM debian:trixie-slim

ARG WITH_KICAD=1
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PATH=/venv/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv yosys iverilog chromium chromium-driver ca-certificates \
 && if [ "$WITH_KICAD" = "1" ]; then apt-get install -y --no-install-recommends kicad; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /pcbflow
COPY . .
RUN python3 -m venv /venv && pip install -e ".[fast,test]"

CMD ["python", "-m", "pytest"]
