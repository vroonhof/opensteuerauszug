FROM python:3.14

RUN apt-get update && apt-get install -y git && \
    pip install --upgrade pip

RUN git clone https://github.com/vroonhof/opensteuerauszug.git

WORKDIR /opensteuerauszug

RUN python3 -m venv .venv && \
    .venv/bin/pip install .[dev] && \
    .venv/bin/pip install git+https://github.com/vroonhof/pdf417-py.git

RUN mkdir -p /data

ARG YEAR=2024
ENV YEAR=${YEAR}
ENV IMPORTER=ibkr

RUN .venv/bin/opensteuerauszug kursliste download --year ${YEAR}

ENV EXTRA_ARGS=""

CMD ["/bin/sh", "-c", ".venv/bin/opensteuerauszug process --importer ${IMPORTER} /data/input.xml --config /data/config.toml --output /data/tax_statement_${YEAR}.pdf --period-from ${YEAR}-01-01 --period-to ${YEAR}-12-31  \"${EXTRA_ARGS}\""]
