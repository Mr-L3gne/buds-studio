# Checklist de teste manual

Itens que dependem de você: ouvir, tocar nos fones, colocar no ouvido, desbloquear a tela ou
aprovar um diálogo do sistema. Marque `[x]` ao concluir e anote o que for diferente do esperado.

Antes de começar:

```sh
flatpak run io.github.mr_l3gne.BudsStudio            # abre a janela
flatpak run io.github.mr_l3gne.BudsStudio --status   # ou teste pela CLI
```

## 0. Dois fones ao mesmo tempo (precisa de um segundo par)

- [ ] Pareie o segundo fone no sistema. No app: barra lateral → "Adicionar novo aparelho" → escolha o fone.
- [ ] Os dois aparecem na barra lateral (e no seletor do título) com nome, bateria e "Conectado".
- [ ] Selecione um, mude o EQ; selecione o outro: o EQ dele não mudou e o primeiro continua "Conectado".
- [ ] Em cada fone, só aparecem as funções do modelo dele (um modelo não testado mostra o aviso "Experimental").
- [ ] "Usar como saída de áudio" em cada um troca a saída do sistema para aquele fone.
- [ ] `flatpak run io.github.mr_l3gne.BudsStudio --status --device "<nome do segundo fone>"` mostra o estado certo.
- [ ] A bandeja lista a bateria dos dois e tem o submenu "Aparelhos".
- [ ] Notificações de bateria baixa e de conexão dizem de qual fone se trata.
- [ ] "Remover aparelhos" tira o fone do app; ele continua pareado em Configurações → Bluetooth.

## 1. Interface

- [ ] A janela abre sem mensagens de erro no terminal.
- [ ] A tela inicial segue a ordem do app do celular (cabeçalho, controle de ruído, Qualidade e efeitos sonoros, Controles de toque, Gerenciar conexões, Recursos avançados, Acessibilidade, Buscar meus fones, Sobre os fones, Recursos do Linux) e cada item abre a subtela com botão de voltar.
- [ ] Janela estreita (< 760 px): coluna única; a seta no topo volta para a lista de aparelhos. Janela larga: barra lateral com os aparelhos.
- [ ] Configurações → Tema: Claro, Escuro e Seguir o sistema mudam na hora e continuam valendo depois de reabrir o app.
- [ ] Preferências → Aparência: escolha "Aurora", "Ondas" e "Areia" e depois uma imagem sua. O fundo muda e os cartões continuam legíveis.
- [ ] Sobre os fones de ouvido mostra nome, modelo, firmware e números de série.
- [ ] Menu → Diagnóstico mostra os pacotes; "Copiar tudo" copia o texto.

## 2. Som e ruído (com os fones no ouvido)

- [ ] Troque entre os 6 presets de EQ e ouça a diferença com uma música.
- [ ] Controle de ruído: desligado, ANC e ambiente soam diferentes.
- [ ] Volume do som ambiente: esquerdo 0 e direito 2 deve soar desigual.
- [ ] Volume extra-alto: ligado deixa o ambiente mais alto; desligado volta ao normal.
- [ ] Balanço: arraste para "E". O som deve ir para a **esquerda**. Depois volte ao centro.
- [ ] Controle de ruído com um fone: com só um fone no ouvido, o ANC continua ligado.

## 3. Toques

- [ ] Desligue "Toque triplo" e dê um toque triplo: nada deve acontecer. Religue e confira que volta a funcionar.
- [ ] Desligue "Controles de toque": nenhum toque deve funcionar. Religue.
- [ ] "Tocar e segurar" → Volume: segurar o esquerdo abaixa e segurar o direito aumenta o volume.
- [ ] "Tocar e segurar" → Alternar controle de ruído, com o ciclo ANC + ambiente: segurar alterna entre os dois, e a tela do app acompanha.

## 4. Recursos

- [ ] Teste de encaixe: com os dois fones no ouvido, em lugar silencioso, clique "Iniciar teste". Aparece o resultado de cada lado.
- [ ] Encontrar meus fones: **tire os fones do ouvido**, clique "Iniciar" e ouça o som. Silenciar o esquerdo para o som desse lado. "Parar" encerra tudo.
- [ ] Detecção no ouvido para chamadas e Modo de jogo: ligar e desligar sem erro.

## 5. Áudio Bluetooth (PipeWire)

- [ ] Com o fone tocando música, página Som → Modo de áudio → "Headset com microfone (HFP)". O microfone do fone aparece no sistema e o codec muda.
- [ ] Volte para "Música (A2DP)". O codec volta para SBC (ou SBC-XQ).
- [ ] Ligue "Trocar automaticamente" e entre numa chamada de voz no Discord. O modo passa para HFP e volta para A2DP alguns segundos depois de sair.
- [ ] EQ de sistema: ligue e mexa nas bandas com música tocando. A saída "Buds Studio EQ" aparece como padrão. Ao desligar ou fechar o app, a saída anterior volta.

## 6. Segundo plano

- [ ] Com a extensão AppIndicator/KStatusNotifierItem ativa, aparece um ícone na bandeja com a bateria e um menu com EQ, ruído e perfis.
- [ ] Fechar a janela mantém o app na bandeja; o menu "Abrir o Buds Studio" traz a janela de volta.
- [ ] Preferências → "Iniciar com o sistema": aceite o pedido do sistema, reinicie a sessão e confira que o app abre minimizado.
- [ ] Notificações: desconectar e reconectar os fones mostra as notificações. Para bateria baixa, suba o limite em Preferências acima da carga atual.
- [ ] Reconexão: desligue os fones (guarde no estojo e feche) e tire de novo. O app reconecta sozinho.

## 7. Perfis

- [ ] Salve um perfil pelo app, troque os ajustes e aplique o perfil. Os ajustes voltam.
- [ ] Exporte os perfis para JSON, apague um e importe o arquivo de volta.
- [ ] `flatpak run io.github.mr_l3gne.BudsStudio --profile "<nome>"` aplica o perfil pelo terminal.

## Se algo falhar

Rode o comando com `--debug` (por exemplo `--preset bass --debug`) ou abra Menu → Diagnóstico e
copie os pacotes. Assim dá para ver o que foi enviado e o que o fone respondeu.
