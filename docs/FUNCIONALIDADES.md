# Funcionalidades do Buds Studio

Cruzamento entre o que os APKs oferecem e o que o protocolo do **Galaxy Buds Core (SM-R410)**
suporta. Os detalhes de bytes estão em [`PROTOCOLO.md`](PROTOCOLO.md), principalmente na §12.

Legenda de status:
- **Testada no fone**: executada pela CLI de dentro do Flatpak instalado, com o SM-R410
  conectado, em 2026-10-14. O fone confirmou com `0x42` ou o valor foi relido no status.
- **Testada sem hardware**: coberta por testes unitários ou executada sem o fone.
- **Não testada**: implementada, mas sem verificação. O passo a passo está em
  [`TESTE-MANUAL.md`](TESTE-MANUAL.md).

## Do app original (APK `pianomgr`)

| Funcionalidade | Origem | Mensagens | Status | Observações |
|---|---|---|---|---|
| Listar fones pareados | Wearable `BluetoothUuidUtil.isSamsungBudsDevice`; `e8.G` | BlueZ D-Bus, UUID `2e73a4ad…f2` | Testada no fone | |
| Conectar / status da conexão | `e8.G`, `e8.F` | RFCOMM via `Profile1` | Testada no fone | |
| Reconectar quando o fone liga | `e8.G` | `Device1.Connected` | Não testada | Testar desligando e ligando os fones |
| Bateria esquerda, direita e estojo | `g8.P`, `g8.l` | `0x60`, `0x61` | Testada no fone | Estojo fora de alcance vem como 255 e aparece como "—" |
| Indicação de carregamento | feature `CHARGING_STATUS`; `g8.P`, `g8.l` | `0x60` byte 7, `0x61` byte 43 | Testada sem hardware | Os fones não estavam carregando no teste |
| No ouvido / fora do ouvido | `g8.l` | `0x60`/`0x61` (placement) | Testada no fone | Os dois estados foram vistos |
| Presets de EQ (6) | `EqualizerActivity`, `glide.c.O` | `0x86` | Testada no fone | Aplicação imediata, sem botão |
| EQ customizado do fone | `EqualizerActivity` | — | Não existe | As 9 barras do app original só desenham o preset (§3.4) |
| Controle de ruído (desligado, ANC, ambiente) | `a3.s` | `0x78`, `0x77` | Testada no fone | Ao tirar os dois fones do ouvido, o fone desligou o controle de ruído sozinho |
| Volume do som ambiente E/D (0–2) | `EnhancementAmbientVolumeActivity`, `g8.g` | `0x82` | Testada no fone (envio) | O fone não confirma; falta ouvir a diferença |
| Volume extra-alto do ambiente (Labs) | `h7.d`, `EnhancementAmbientVolumeActivity` | `0x96` + `0x82` | Testada no fone (envio) | Sem confirmação; estado deduzido do volume 4 [INFERIDO] |
| Controle de ruído com um fone | `NoiseControlsWithOneEarBudActivity`, `g8.E` | `0x6F` | Testada no fone | |
| Som ambiente durante chamadas | `AmbientDuringCallsActivity` | `0x8B` | Testada no fone | |
| Travar / destravar toques | `TouchControlsActivity`, `g8.r` | `0x90` | Testada no fone | |
| Gestos (toque, duplo, triplo, segurar, chamadas) | `TouchControlsActivity`, `g8.r` | `0x90` | Testada no fone | Que 1 = gesto ativo foi conferido pela leitura e pelo eco; falta confirmar tocando |
| Ação do "tocar e segurar" por lado | `TouchAndHoldActivity`, `g8.N` | `0x92` | Testada no fone | Só "alternar ruído" e "volume"; as demais opções dependem do celular |
| Modos do ciclo do "tocar e segurar" | `TouchAndHoldActivity`, `g8.M` | `0x79` | Testada no fone | O mesmo ciclo vale para os dois lados |
| Detecção no ouvido para chamadas | `InEarDetectionActivity`, `AdvancedFeatureActivity` | `0x6E` (invertido) | Testada no fone | |
| Encontrar meus fones | `FindMyEarbudsActivity`, `K7.b` | `0xA6`, `0xA1` | Testada no fone | Confirmado por ack; falta ouvir o som. Para sozinho em 3 min |
| Silenciar esquerdo/direito na busca | `K7.b.d` | `0xA2` | Testada no fone (envio) | Sem confirmação |
| Teste de encaixe | `FitTestActivity` | `0x9D`, `0x9E` | Testada no fone (parcial) | A recusa sem os fones no ouvido funcionou; falta o teste completo |
| Modo de jogo (Labs) | `GamingModeActivity` | `0x85` | Testada no fone | |
| Balanço esquerdo/direito | `HearingEnhancementsActivity` | `0x8F` | Testada no fone | O fone confirma, embora o APK não espere ack |
| Informações do dispositivo | `AboutEarbudsActivity`, `g8.b0`, `g8.j`, `g8.f` | `0x68`, `0x29`, `0xCD` | Testada no fone | Modelo, firmware, séries dos fones e do estojo, endereço |

## Extras (não existem no app original)

| Funcionalidade | Origem | Status | Observações |
|---|---|---|---|
| Perfil de áudio A2DP ↔ HFP e codec | extra (PipeWire `pw-dump`/`pw-cli`) | Testada sem hardware (parcial) | Análise do `pw-dump` real em teste unitário; permissão de escrita validada no sandbox. A troca real não foi testada porque o áudio A2DP do fone tinha caído |
| Troca automática para HFP quando um app grava | extra | Testada sem hardware | Detecção de gravação em teste unitário. Desligada por padrão |
| EQ de sistema (10 bandas, PipeWire filter-chain) | extra | Testada sem hardware | No sandbox, com a saída do notebook: cria "Buds Studio EQ", vira padrão, muda o ganho ao vivo e restaura a saída anterior. Desligado por padrão |
| Curvas prontas do EQ de sistema (Plana, Graves, Agudos, Vozes, Loudness, Suave) | extra | Testada sem hardware | Seletor "Curva" na tela do EQ do computador e `--system-eq-preset`. Mexer num slider troca o seletor para "Personalizada". Verificada na interface real (runtime GNOME 51) |
| Evitar distorção no EQ de sistema (compensação de volume) | extra | Testada sem hardware | Nó `preamp` (`linear`) antes das bandas, com o volume reduzido pelo pico real da curva (resposta dos filtros somada, não só o maior ganho). Ligado por padrão; atualiza ao vivo via `pw-cli`. Conferido no PipeWire do computador: o grafo carrega e o `preamp:Mult` muda sem reiniciar |
| Perfis salvos (aplicar, exportar, importar JSON) | extra | Testada no fone + sem hardware | `--profile` aplicou EQ e modo de jogo no fone; exportar/importar em teste unitário |
| Ícone na bandeja (StatusNotifierItem) | extra | Não testada | Com a tela bloqueada não havia `StatusNotifierWatcher`; o app seguiu normal sem ele |
| Notificações (bateria baixa, conectado/desconectado) | extra | Não testada | |
| Iniciar com o sistema minimizado (portal Background) | extra | Não testada | O portal pede confirmação na primeira vez |
| CLI (`--status`, `--preset`, `--anc`, `--profile`, `--set` etc.) | extra | Testada no fone | Funciona sozinha ou repassando à instância aberta |
| Português do Brasil (padrão) e inglês | extra (gettext) | Testada sem hardware | Os dois idiomas conferidos na CLI |
| Modo diagnóstico | extra | Testada no fone | `--debug` e a tela "Diagnóstico" mostram os pacotes em hex |
| Suporte a vários modelos | Wearable `b7.l.a` | Testada sem hardware | Só o Core foi validado; os demais aparecem como experimentais |
| Interface no estilo do Galaxy Wearable | `DESIGN-REFERENCIA.md` | Testada no fone | Tela inicial, subtelas e nomes do app original; controle segmentado e Equalizador mudaram o fone pela interface (ack `0x78`/`0x86`). Capturas em `screenshots/` |
| Janela estreita (coluna única) e larga (barra lateral) | extra (`AdwBreakpoint`) | Testada sem hardware | Capturas em 400 px e 1100 px, sem avisos de largura |
| Tema Claro / Escuro / Seguir o sistema | extra (`AdwStyleManager`) | Testada sem hardware | Muda na hora; testes unitários e conferência na janela real |
| Vários fones ao mesmo tempo | extra | Testada sem hardware (simulado) + com 1 fone real | Uma conexão RFCOMM e um estado por fone, seleção sem desconectar os outros (testes com transporte simulado). Com dois fones reais: não testada |
| Seletor de aparelhos (topo e barra lateral) com bateria e status | Gaveta do app original | Testada no fone (1 fone) | |
| Adicionar novo aparelho / Remover aparelhos | Gaveta do app original | Testada sem hardware | Remover só tira do app; não despareia |
| Usar como saída de áudio | extra (PipeWire/BlueZ) | Não testada | Conecta o A2DP pelo BlueZ se preciso e define a saída padrão |
| `--device <nome|endereço>` na CLI | extra | Testada no fone | Por nome e por endereço; nome inexistente dá erro |

## O que ficou de fora e por quê

| Item | Motivo |
|---|---|
| Atualização de firmware (FOTA), reset de fábrica | Proibido pelas regras do projeto |
| Autodiagnóstico, coleta de logs e coredump | Escrita de manutenção; fora do escopo de áudio |
| EQ customizado no fone | O protocolo do Core não tem; só presets fixos |
| Pausa automática ao tirar do ouvido | O Core não tem a feature: `AUTO_PAUSE_RESUME` exige revision ≥ 9999 em `g8.l` |
| Detecção de voz / conversa (`0x7A`/`0x7B`) | O plugin não mostra essa tela para o Core (`CardVoiceDetect` não é criado) |
| Áudio 360 e rastreamento de cabeça | O Core não tem as features `_360_AUDIO`/`HEAD_TRACKING_ON_OFF` |
| Nível de redução de ruído (`0x83`) | Só existe na API para apps de terceiros (`D8.d`), sem tela no plugin; o valor atual é mantido no `0x82` |
| Tom do ambiente e "conversation boost" do `0x82` | Sem tela própria para o Core no plugin; o app repassa os valores lidos |
| Bixby / ativação por voz (`0x97`) | Depende do assistente do celular Samsung |
| Conexão contínua entre aparelhos Samsung (`0xAF`) | Feature `SEAMLESS_CONNECTION` ausente no Core e dependente de conta Samsung |
| Voice boost e normalização de volume (`0x6A`) | Processados no celular (SoundAlive) |
| Opções do "tocar e segurar" que abrem apps do celular | Assistente, intérprete, mindfulness, Spotify e outros apps não existem no Linux |
| Adaptação ao ouvido, teste de audição, alongamento do pescoço | Features ausentes no Core |
| SoundCraft | Integração com apps do celular |
| Envio de `0x88` (informação do host) | Não foi necessário no hardware |
