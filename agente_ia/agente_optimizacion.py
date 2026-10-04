#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║       AGENTE DE OPTIMIZACIÓN IA — banco_telemetria           ║
║                                                              ║
║  Flujo:                                                      ║
║  1. Conecta a PostgreSQL (usuario de solo-lectura)           ║
║  2. Extrae metadata estructural + perfil de cardinalidad      ║
║  3. Detecta consultas lentas vía pg_stat_statements          ║
║  4. Consulta a la API de OpenAI / Google Gemini con          ║
║     el contexto completo                                     ║
║  5. Muestra recomendaciones de índices o reescritura         ║
╚══════════════════════════════════════════════════════════════╝

EJECUCIÓN:
    python agente_ia/agente_optimizacion.py

REQUISITOS:
    pip install psycopg2-binary openai python-dotenv rich requests

VARIABLES DE ENTORNO (archivo agente_ia/.env):
    PG_HOST=localhost
    PG_PORT=5433
    PG_DB=banco_telemetria
    PG_USER=openmetadata_reader
    PG_PASS=om_reader_2026
    OPENAI_API_KEY=sk-...         ← o usa GEMINI_API_KEY
    AI_PROVIDER=openai            ← 'openai' o 'gemini'
    AI_MODEL=gpt-4o-mini          ← o 'gemini-1.5-flash'
    LOKI_URL=http://localhost:3100
"""

import os
import sys
import json
import time
import textwrap
from datetime import datetime

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

# ── Rich para salida visual en terminal ─────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    from rich import print as rprint
    RICH = True
    console = Console()
except ImportError:
    RICH = False
    console = None
    def rprint(*args, **kwargs): print(*args)

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Configuración ────────────────────────────────────────────────────────────
PG_CONFIG = {
    "host":     os.getenv("PG_HOST", "localhost"),
    "port":     int(os.getenv("PG_PORT", "5433")),
    "dbname":   os.getenv("PG_DB", "banco_telemetria"),
    "user":     os.getenv("PG_USER", "openmetadata_reader"),
    "password": os.getenv("PG_PASS", "om_reader_2026"),
}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
AI_PROVIDER    = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL       = os.getenv("AI_MODEL", "gpt-4o-mini")
LOKI_URL       = os.getenv("LOKI_URL", "http://localhost:3100")

TABLES = ["clientes", "cuentas", "transacciones"]


# ════════════════════════════════════════════════════════════════════════════
# 1. EXTRACCIÓN DE METADATA ESTRUCTURAL
# ════════════════════════════════════════════════════════════════════════════
def extract_schema(conn) -> dict:
    """Lee columnas, tipos, restricciones y FK del esquema público."""
    schema = {}
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        for table in TABLES:
            cur.execute("""
                SELECT
                    c.column_name,
                    c.data_type,
                    c.character_maximum_length,
                    c.is_nullable,
                    c.column_default,
                    (SELECT string_agg(tc.constraint_type, ', ')
                     FROM information_schema.table_constraints tc
                     JOIN information_schema.key_column_usage kcu
                       ON tc.constraint_name = kcu.constraint_name
                     WHERE kcu.table_name = %s
                       AND kcu.column_name = c.column_name
                    ) AS constraints
                FROM information_schema.columns c
                WHERE c.table_name = %s AND c.table_schema = 'public'
                ORDER BY c.ordinal_position;
            """, (table, table))
            schema[table] = [dict(r) for r in cur.fetchall()]
    return schema


# ════════════════════════════════════════════════════════════════════════════
# 2. PERFIL DE CARDINALIDAD (Simula el Data Profiler de OpenMetadata)
# ════════════════════════════════════════════════════════════════════════════
def extract_profiling(conn) -> dict:
    """
    Para cada tabla y columna, calcula:
      - total_rows
      - distinct_values (cardinalidad)
      - null_pct
      - selectivity = distinct / total  (1.0 = clave única; 0.03 = columna de baja cardinalidad)
    """
    profile = {}
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        for table in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            total = cur.fetchone()[0]
            profile[table] = {"total_rows": total, "columns": {}}

            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = %s AND table_schema = 'public'
                ORDER BY ordinal_position;
            """, (table,))
            cols = [r[0] for r in cur.fetchall()]

            for col in cols:
                try:
                    cur.execute(f"""
                        SELECT
                            COUNT(DISTINCT {col})   AS distinct_vals,
                            SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)::float
                                / NULLIF(COUNT(*), 0) * 100 AS null_pct
                        FROM {table};
                    """)
                    row = cur.fetchone()
                    distinct = row[0] or 0
                    null_pct  = round(row[1] or 0, 2)
                    selectivity = round(distinct / total, 6) if total > 0 else 0
                    profile[table]["columns"][col] = {
                        "distinct_values": distinct,
                        "null_pct": null_pct,
                        "selectivity": selectivity,
                        "recommendation": _index_hint(selectivity, col),
                    }
                except Exception:
                    pass
    return profile


def _index_hint(selectivity: float, col: str) -> str:
    """Heurística de cardinalidad para recomendar tipo de índice."""
    if selectivity > 0.95:
        return "ALTA cardinalidad → B-Tree o Hash ideal (búsqueda puntual exacta)"
    elif selectivity > 0.30:
        return "MEDIA cardinalidad → B-Tree útil para rangos y ORDER BY"
    elif selectivity > 0.05:
        return "BAJA cardinalidad → Evalúa si el optimizador preferirá Seq Scan"
    else:
        return "MUY BAJA cardinalidad → Índice individual probablemente inútil; " \
               "considerar Bitmap combinado con otro índice"


# ════════════════════════════════════════════════════════════════════════════
# 3. CONSULTAS LENTAS DESDE pg_stat_statements
# ════════════════════════════════════════════════════════════════════════════
def extract_slow_queries(conn, top_n: int = 5) -> list:
    """Devuelve las N consultas con mayor tiempo total de ejecución."""
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT
                LEFT(query, 300)            AS query_text,
                calls,
                ROUND(total_exec_time::numeric, 2)  AS total_ms,
                ROUND(mean_exec_time::numeric, 2)   AS mean_ms,
                ROUND(stddev_exec_time::numeric, 2) AS stddev_ms,
                rows
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND calls > 2
            ORDER BY total_exec_time DESC
            LIMIT %s;
        """, (top_n,))
        return [dict(r) for r in cur.fetchall()]


# ════════════════════════════════════════════════════════════════════════════
# 4. ÍNDICES ACTUALES
# ════════════════════════════════════════════════════════════════════════════
def extract_indexes(conn) -> list:
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = ANY(%s)
            ORDER BY tablename, indexname;
        """, (TABLES,))
        return [dict(r) for r in cur.fetchall()]


# ════════════════════════════════════════════════════════════════════════════
# 5. IMPRIMIR REPORTE EN TERMINAL
# ════════════════════════════════════════════════════════════════════════════
def print_report(schema, profiling, slow_queries, indexes):
    """Muestra un resumen visual antes de llamar a la IA."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rprint(f"\n[bold cyan]══════════════════════════════════════════════════")
    rprint(f"  AGENTE DE METADATA — banco_telemetria  [{ts}]")
    rprint(f"══════════════════════════════════════════════════[/bold cyan]\n")

    # Tabla de perfilado por tabla
    for table in TABLES:
        prof = profiling.get(table, {})
        rprint(f"[bold yellow]📊 TABLA: {table}[/bold yellow]  "
               f"({prof.get('total_rows', 0):,} filas)")
        t = Table(show_header=True, header_style="bold magenta")
        t.add_column("Columna");   t.add_column("Distintos", justify="right")
        t.add_column("Nulos %", justify="right"); t.add_column("Selectividad", justify="right")
        t.add_column("Recomendación", no_wrap=False)
        for col, m in prof.get("columns", {}).items():
            t.add_row(
                col,
                f"{m['distinct_values']:,}",
                f"{m['null_pct']}%",
                f"{m['selectivity']:.4f}",
                m["recommendation"],
            )
        console.print(t) if RICH else None
        rprint()

    # Índices existentes
    rprint("[bold yellow]🗂  ÍNDICES ACTUALES:[/bold yellow]")
    for idx in indexes:
        rprint(f"  • [{idx['tablename']}]  {idx['indexname']}")
        rprint(f"    {idx['indexdef']}")
    rprint()

    # Queries lentas
    rprint("[bold yellow]🐢 TOP CONSULTAS LENTAS (pg_stat_statements):[/bold yellow]")
    for i, q in enumerate(slow_queries, 1):
        rprint(f"  [{i}] calls={q['calls']}  total={q['total_ms']} ms  "
               f"avg={q['mean_ms']} ms  rows={q['rows']}")
        rprint(f"      {textwrap.shorten(q['query_text'], 120)}")
    rprint()


# ════════════════════════════════════════════════════════════════════════════
# 6. CONSTRUCCIÓN DEL PROMPT PARA LA IA
# ════════════════════════════════════════════════════════════════════════════
def build_prompt(schema, profiling, slow_queries, indexes) -> str:
    prompt = textwrap.dedent(f"""
    Eres un experto DBA (Database Administrator) especializado en optimización de PostgreSQL.
    Analiza el siguiente contexto de la base de datos bancaria "banco_telemetria" y proporciona
    recomendaciones concretas y trazables de optimización mediante índices.

    ══════════════════════════
    1. ESQUEMA DE TABLAS
    ══════════════════════════
    {json.dumps(schema, indent=2, default=str)}

    ══════════════════════════
    2. PERFIL DE CARDINALIDAD
    (selectivity=1.0 → clave única; selectivity≈0 → muy pocos valores distintos)
    ══════════════════════════
    {json.dumps(profiling, indent=2, default=str)}

    ══════════════════════════
    3. ÍNDICES YA EXISTENTES
    ══════════════════════════
    {json.dumps(indexes, indent=2, default=str)}

    ══════════════════════════
    4. TOP CONSULTAS LENTAS (pg_stat_statements)
    ══════════════════════════
    {json.dumps(slow_queries, indent=2, default=str)}

    ══════════════════════════
    INSTRUCCIONES DE RESPUESTA
    ══════════════════════════
    Para cada consulta lenta o patrón de acceso identificado:
    1. Explica EN SIMPLE por qué es lenta (Seq Scan, Sort en memoria, etc.).
    2. Propón el tipo de índice más adecuado (B-Tree, Hash, GIN, compuesto)
       justificando con la selectividad y el tipo de operación (=, BETWEEN, OR, etc.).
    3. Proporciona el DDL exacto y listo para ejecutar.
    4. Estima el impacto esperado (reducción de Seq Scan a Index Scan, eliminación de Sort, etc.).
    5. Si una columna tiene selectividad MUY BAJA (<0.05), advierte por qué NO crear un índice individual.
    6. Si detectas que un índice existente es redundante o contraproducente, indícalo.

    Sé concreto, técnico y usa los nombres reales de tablas y columnas del esquema.
    """)
    return prompt.strip()


# ════════════════════════════════════════════════════════════════════════════
# 7. LLAMADA A LA IA
# ════════════════════════════════════════════════════════════════════════════
def call_openai(prompt: str) -> str:
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content":
                "Eres un experto DBA PostgreSQL. Responde en español de forma clara y estructurada."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=2048,
    )
    return response.choices[0].message.content


def call_gemini(prompt: str) -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{AI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def call_ai(prompt: str) -> str:
    rprint("[bold cyan]🤖 Consultando a la IA...[/bold cyan]")
    if AI_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            return "[ERROR] GEMINI_API_KEY no configurada en agente_ia/.env"
        return call_gemini(prompt)
    else:
        if not OPENAI_API_KEY:
            return "[ERROR] OPENAI_API_KEY no configurada en agente_ia/.env"
        return call_openai(prompt)


# ════════════════════════════════════════════════════════════════════════════
# 8. MAIN
# ════════════════════════════════════════════════════════════════════════════
def main():
    rprint("\n[bold green]▶ Conectando a PostgreSQL...[/bold green]")
    try:
        conn = psycopg2.connect(**PG_CONFIG)
    except Exception as e:
        rprint(f"[bold red]✗ No se pudo conectar: {e}[/bold red]")
        rprint("[dim]¿Están los contenedores levantados? (docker compose up -d)[/dim]")
        sys.exit(1)

    with conn:
        rprint("[bold green]✓ Conexión exitosa. Extrayendo metadata...[/bold green]")
        t0 = time.time()

        schema       = extract_schema(conn)
        profiling    = extract_profiling(conn)
        slow_queries = extract_slow_queries(conn, top_n=5)
        indexes      = extract_indexes(conn)

        elapsed = round(time.time() - t0, 2)
        rprint(f"[green]✓ Metadata extraída en {elapsed}s[/green]\n")

    # Reporte visual en terminal
    print_report(schema, profiling, slow_queries, indexes)

    # Guardar contexto JSON para trazabilidad
    context = {
        "timestamp": datetime.now().isoformat(),
        "schema": schema,
        "profiling": profiling,
        "existing_indexes": indexes,
        "slow_queries": slow_queries,
    }
    out_path = os.path.join(os.path.dirname(__file__), "ultimo_contexto.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2, default=str, ensure_ascii=False)
    rprint(f"[dim]📄 Contexto guardado en: {out_path}[/dim]\n")

    # Llamada a la IA
    prompt       = build_prompt(schema, profiling, slow_queries, indexes)
    recomendaciones = call_ai(prompt)

    # Resultado
    rprint("\n[bold cyan]══════════════════════════════════════════════════")
    rprint("  RECOMENDACIONES DE OPTIMIZACIÓN GENERADAS POR IA")
    rprint("══════════════════════════════════════════════════[/bold cyan]\n")
    rprint(recomendaciones)

    # Guardar reporte final
    report_path = os.path.join(os.path.dirname(__file__), "reporte_ia.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Reporte de Optimización IA\n")
        f.write(f"**Generado:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(recomendaciones)
    rprint(f"\n[green]📝 Reporte guardado en: {report_path}[/green]")


if __name__ == "__main__":
    main()
