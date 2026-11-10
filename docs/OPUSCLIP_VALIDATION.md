# Validar a integração OpusClip (no PC, depois do OAuth)

## Como a integração funciona

O engine `opusclip` **não depende de nomes de tools fixos**. O Python chama `claude -p` com:

- `--allowedTools mcp__opusclip` (só as tools deste MCP; nada de Bash, ficheiros nem web);
- instruções que descrevem o objetivo de cada passo;
- um JSON schema de resposta.

O Claude escolhe as tools certas do MCP. Isto aguenta mudanças de nomes no MCP do OpusClip.

| Passo | O que pede ao Claude | Consome créditos |
|---|---|---|
| submit | ver créditos, criar **um** projeto com o URL (9:16, reframe, legendas, duração) | sim (único passo) |
| status | ler o estado do projeto | não |
| fetch | listar clips + virality, exportar os 3 melhores, devolver links | export pode consumir: confirmar |
| download | descarregar os MP4 (feito pelo Python) | não |

Regras no system prompt: nunca publicar/agendar, nunca apagar, no máximo um projeto, sem inventar valores.
O `project_id` fica em `outputs/<vod>/opusclip/state.json`: voltar a correr retoma sem submeter outra vez.

## O que confirmar (por esta ordem, sem gastar créditos)

1. `python -m clipper doctor` → `MCP opusclip ligado` ✅.
2. `python -m clipper opusclip-tools` → abre `docs/opusclip_tools.md` e confirma:
   - [ ] existe uma tool de **créditos/uso** (ex.: `usage`). Se não existir, `credits_used` fica `null`
     e vês o consumo no site do OpusClip.
   - [ ] existe uma tool de **submeter projeto a partir de URL** (ex.: `submit_project`) e que aceita YouTube/Twitch.
   - [ ] existe uma tool de **estado do projeto**.
   - [ ] existe uma tool que **lista clips com virality score** (ex.: `list_clips`) e se dá início/fim no vídeo original.
   - [ ] existe uma tool de **export** (ex.: `export_clip`) e se **o export consome créditos**.
   - [ ] quais tools publicam/agendam (ex.: `schedule_publish`). O sistema nunca as deve usar.
3. Manda-me o `docs/opusclip_tools.md`. Se algum ponto falhar, ajusto os prompts em
   `clipper/engines/opusclip.py` (sem mudar a arquitetura).

## Se algo correr mal no primeiro `compare`

- `OpusClip não devolveu project_id` → nada foi gasto. Vê a mensagem `notes`.
- Timeout à espera → volta a correr o mesmo comando: retoma o mesmo projeto.
- Clips sem `download_url` → o `report.md` mostra-os como não exportados; vê `opusclip/state.json`.
- Para recomeçar de raiz o mesmo VOD (gasta créditos de novo!): apagar `outputs/<vod>/opusclip/state.json`.
