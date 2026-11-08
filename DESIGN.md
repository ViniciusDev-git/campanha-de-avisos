# Design

Mesa de Lâmpadas, escolhida entre três protótipos navegáveis. A campanha é um painel: cada contato é uma lâmpada, e o trabalho é vê-lo acender. Fonte de verdade: `disparo/ui/app.css`.

## Cena de uso

Equipe de cobrança ou atendimento, escritório claro, janela aberta por horas ao lado de telefone e planilha. Por isso a área de tarefa é clara e só o painel é escuro: o olhar encontra o andamento de longe, sem que a tela inteira vire um bloco preto.

## Estrutura

Três colunas: etapas (216px), tarefa (flexível), painel (420px). Durante o disparo a tarefa encolhe para 372px e o painel ocupa o resto. Essa troca, em 0,5s, é o único movimento coreografado. Janela mínima: 1080 x 700.

## Cor

| Papel | Valor |
|---|---|
| Esmalte, fundo de tarefa | `#EFF1EF` |
| Esmalte escuro, coluna de etapas | `#E4E8E5` |
| Baquelite, painel e botão primário | `#1A2023` |
| Lâmpada acesa, texto sobre botão | `#F6E8C4` |
| Âmbar, só para "agora" | `#C97C1E` |
| Alerta | `#C4492F` |

Âmbar marca a etapa atual e o que está em andamento, nunca decoração. Situação nunca depende só de cor: há sempre texto, e "Sem WhatsApp" é uma lâmpada vazada.

## Tipo

Figtree variável (SIL Open Font License), embutida no programa, uma família só. Corpo 16px, títulos 32px peso 500, números de andamento 44px. Algarismos tabulares em toda a interface.

## Componentes

- Botão primário de baquelite com texto opalino; secundário só com fio; desabilitado em esmalte.
- Sem cartões. Grupos se separam por fio de 1px e espaço.
- Ação principal sempre no pé da coluna.
- Confirmação de envio real é inline, em fundo opalino, nunca modal.
- Bloqueio aparece como frase com um link "Resolver", não como botão morto sem motivo.

## Movimento

Lâmpada acende com brilho que assenta em 900ms. Telas chegam em 250ms. `prefers-reduced-motion` desliga tudo.

## Voz

Frases curtas, sem termos técnicos, sem urgência. Variáveis aparecem como `[Primeiro nome]`; o formato do motor nunca é mostrado a quem opera. Toda parada diz o que aconteceu e o que fazer.
