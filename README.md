# Shorts — Os Achadinhos da Shopee

Aplicativo privado para organizar produtos, pesquisar referências públicas e editar vídeos próprios/licenciados/autorizados em formato vertical 9:16.

## Importante sobre o MVP
- A pesquisa do YouTube usa a YouTube Data API v3 apenas para localizar vídeos e mostrar metadados/links. Ela **não baixa** vídeos do YouTube.
- Para editar, envie um arquivo que você tenha direito de usar.
- O corte só é exportado se todos os seis critérios obrigatórios forem confirmados.
- A lista de aprovação é uma revisão humana. Esta primeira versão não afirma detectar automaticamente logotipos, marcas d'água ou violência por visão computacional.
- O áudio original é mantido; não há geração de voz nem música.
- A chave Groq é opcional e serve para sugerir palavras-chave. Sem ela, o sistema usa palavras-chave locais simples.
- As chaves são inseridas no painel, não no deploy. São criptografadas no SQLite usando `APP_SECRET`.

## Requisitos
- Python 3.10+
- FFmpeg e ffprobe instalados no servidor para renderização.
- cPanel com Setup Python App ou Application Manager/Passenger habilitado.
- Para busca do YouTube: chave YouTube Data API v3 inserida em Configurações.
- Para palavras-chave com IA: chave Groq inserida em Configurações (opcional).

## Primeiro acesso
O usuário/senha iniciais são definidos por `ADMIN_USER` e `ADMIN_PASSWORD`.
**Altere ambos antes de publicar.** Se não definir variáveis, o padrão é `admin` / `change-me-now`, que não deve permanecer em produção.

## Deploy em cPanel
1. Crie o subdomínio `shorts.osachadinhosdashopee.com.br` no cPanel.
2. Extraia o projeto em uma pasta fora de `public_html`, se possível (por exemplo `shorts_app`).
3. No cPanel, procure **Setup Python App** ou **Application Manager**. A disponibilidade depende da hospedagem.
4. Crie aplicação Python 3.10+ apontando para a pasta do projeto e associe o subdomínio.
5. Startup file: `passenger_wsgi.py`; entry point: `application`.
6. Instale as dependências com `pip install -r requirements.txt` no ambiente virtual.
7. Configure no painel do cPanel as variáveis `APP_SECRET`, `ADMIN_USER`, `ADMIN_PASSWORD` e `MAX_UPLOAD_MB`.
8. Solicite ao suporte da hospedagem a instalação/liberação de `ffmpeg` e `ffprobe`, incluindo codecs `libx264` e `aac`.
9. Confirme se a hospedagem permite uploads grandes, execução de subprocessos e tempo suficiente para renderizar vídeos.
10. Reinicie a aplicação.

### Limitação importante do cPanel compartilhado
O painel pode hospedar a interface e a API se Python/Passenger estiver habilitado. Mas renderização de vídeo pode não funcionar em hospedagem compartilhada por falta de FFmpeg, limites de CPU/memória/tempo, ou bloqueio de processos. Se o provedor não liberar esses recursos, mantenha o painel no cPanel e execute o processamento em Railway/VPS. Não é possível garantir compatibilidade sem conhecer o plano do servidor.

## Deploy no Railway
1. Envie o projeto para um repositório GitHub privado.
2. Crie um projeto Railway a partir do repositório.
3. Adicione um Volume montado em `/app/data` e outro em `/app/storage` (ou um volume único em `/app/data` e ajuste os caminhos).
4. Cadastre `APP_SECRET`, `ADMIN_USER`, `ADMIN_PASSWORD`, `MAX_UPLOAD_MB`.
5. O Dockerfile instala FFmpeg automaticamente.
6. Faça o deploy e acesse a URL gerada.

## APIs no painel
Entre em **Configurações**:
- `GROQ_API_KEY` — opcional, para expandir palavras-chave.
- `YOUTUBE_API_KEY` — opcional, para pesquisar vídeos públicos e exibir título/canal/link/miniatura.
As chaves ficam armazenadas criptografadas no banco de dados local. Não as coloque no GitHub.

## Critérios obrigatórios para exportar
- Produto corresponde exatamente ao anúncio.
- Sem marca d'água de terceiros.
- Sem logotipo de outra marca.
- Cena nítida e contextualizada.
- Sem violência ou conteúdo impróprio.
- Direitos de uso do vídeo confirmados.

Se qualquer critério não for marcado, o corte é rejeitado e nenhum MP4 é criado.

## Escopo desta versão
Esta é uma primeira versão funcional de painel, cadastro de produto, pesquisa de referências, upload de vídeo autorizado, checklist rígido e exportação de cortes MP4. Detecção automática por IA de cenas, OCR de logotipos/marcas d'água, análise de violência e sincronização automática de legendas ainda exigem integração e testes adicionais.
