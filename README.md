# LLM Arena

Arena 2D estilo *Street Fighter* onde dois LLMs lutam **escrevendo código Python**. A cada golpe os dois
modelos recebem o mesmo mini-desafio de programação; o primeiro que entregar código que roda no sandbox e
passa nos testes acerta o oponente. O espectador vê os bonecos, o código de cada lado sendo escrito token a
token, o enunciado e o resultado dos testes.

## Regras

| Regra | Valor |
|---|---|
| Vida | 100 HP por lutador, melhor de 3 rounds, 90 s por round ou KO |
| Dano | fácil 10, médio 20, difícil 35 |
| Golpe errado | abre **contra-ataque**: o próximo golpe válido do oponente no mesmo desafio causa +50 % |
| Erro de API (429/5xx/timeout) | golpe perdido, sem abrir contra-ataque |
| Custo | `max_tokens` 2500, até 4 tentativas por desafio, 12 golpes por round por lutador |

## Modo "problema personalizado" (vantagem)

Na tela de setup dá para digitar o seu próprio problema. Um **juiz** (Claude Opus 5.5 por padrão, ou o
modelo definido em `JUDGE_PROVIDER`/`JUDGE_MODEL`) transforma o texto em um desafio testável: assinatura,
enunciado, 4 a 6 casos de teste e uma solução de referência que precisa passar no sandbox antes de a luta
começar. O desafio aparece na tela para conferência e a luta segue a regra da **vantagem**:

- Quem resolve primeiro acerta um golpe normal e ganha a vantagem.
- Enquanto tem a vantagem, cada tentativa falha do oponente vira um **golpe livre** (mesmo dano).
- Quando o oponente também resolve, a vantagem acaba e o juiz entrega uma variação **mais difícil**
  (nível 2, 3, ...). A próxima variação é gerada em segundo plano durante a fase atual; se o juiz falhar,
  entra um desafio do banco.
- Erro de API do oponente não dá golpe livre. Não há contra-ataque neste modo.

Desafios ficam em `challenges/bank.yaml` (39 hoje), sorteados sem repetir no round. A solução de referência
nunca vai para o modelo; `uv run llm-arena verify-challenges` prova que todos os testes são resolvíveis.

## Rodando

```bash
cp .env.example .env            # coloque ANTHROPIC_API_KEY e/ou OPENROUTER_API_KEY
uv sync --extra dev
uv run llm-arena serve          # http://127.0.0.1:8080
uv run llm-arena serve --fake   # modo demo sem chaves (modelos "demo/*" resolvem com a referência)
uv run pytest                   # testes
```

Com Docker (na VPS):

```bash
docker compose up -d --build
docker compose exec arena python scripts/probe_sandbox.py   # mostra o que o isolamento consegue fazer
```

Modelos selecionáveis ficam em `config/models.yaml`; só aparecem os provedores com chave no `.env`.

## Segurança do sandbox

Cada golpe roda em um subprocesso `python3 -I -S` separado, em diretório temporário, com `stdin` fechado,
ambiente vazio (sem chaves), `RLIMIT_AS` 256 MiB, `RLIMIT_CPU` 3 s, `RLIMIT_NPROC`, `RLIMIT_FSIZE` 1 MiB,
timeout de 3,5 s e `killpg` em caso de estouro. Antes de rodar, o código passa por uma allowlist de imports
(`math`, `itertools`, `collections`, `functools`, `string`, `re`, `heapq`, `bisect`, ...) e bloqueio de
`open`, `exec`, `eval`, `__import__`, `input`, etc.

**Rede:** na inicialização o app testa `unshare -n` e `unshare -Urn`; se um deles funcionar, o subprocesso
roda sem rede. No host isso funciona direto. Dentro do Docker o perfil seccomp padrão bloqueia `unshare`,
então o sandbox sobe sem isolamento de rede (as outras defesas continuam) e registra um aviso. Se quiser o
isolamento de rede dentro do container, a opção é relaxar o seccomp do serviço no `docker-compose.yml`
(`security_opt` com perfil `unconfined`), uma decisão de segurança que fica a seu critério. Verificado nesta
VPS: com o perfil padrão o probe reporta `unshare` indisponível e rede aberta no subprocesso; com o perfil
relaxado o `unshare -Urn` passa a funcionar e a rede fica bloqueada (`Network is unreachable`).

Não exponha a porta publicamente sem um reverse proxy com autenticação: qualquer pessoa com acesso pode
iniciar partidas e gastar tokens das suas chaves.

## Arquitetura

- `src/llmarena/arena/round.py` — o árbitro: único coroutine que altera o estado do round; consome uma fila
  de resultados, aplica dano, cancela os streams em voo e sorteia o próximo desafio.
- `src/llmarena/arena/fighter.py` — um lutador: stream do LLM → extração do código → checagem estática →
  sandbox → resultado na fila. Retenta o mesmo desafio com o erro no prompt.
- `src/llmarena/sandbox/` — executor e `runner_script.py` (só stdlib, aplica os rlimits em si mesmo).
- `src/llmarena/providers/` — Anthropic (SDK oficial, streaming, `effort: low`) e OpenRouter (httpx + SSE).
- `src/llmarena/protocol.py` — contrato dos eventos WebSocket; o cliente só renderiza.
- `src/llmarena/persistence/` — SQLite (partidas, rounds, golpes) e o ranking em `/api/leaderboard`.
- `static/` — HTML/JS/Canvas sem build: arena, painéis de código, ranking.

## API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/models` | provedores e modelos disponíveis |
| POST | `/api/matches` | `{left:{provider,model}, right:{...}, problem_id?}` → `{match_id}` (409 se já há luta) |
| GET/DELETE | `/api/matches/current` | estado da luta atual / abortar |
| GET | `/api/matches?limit=20` | últimas partidas |
| GET | `/api/matches/{id}/golpes` | todos os golpes de uma partida, com o código |
| GET | `/api/judge` | se há juiz configurado e qual modelo |
| POST | `/api/problems/generate` | `{statement}` → desafio gerado pelo juiz (`problem_id` para a luta) |
| GET | `/api/matches/{id}/challenges` | variações geradas pelo juiz numa partida |
| GET | `/api/leaderboard` | ranking por modelo |
| WS | `/ws` | eventos ao vivo (`state_snapshot` ao conectar) |
