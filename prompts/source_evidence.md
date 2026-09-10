# Klassificér kandidater

Vurdér hver handle i sources uafhængigt mod spørgsmålets emne, efterspurgte
relation og filtre. Adskil denne klassifikation fra udvælgelsen af det endelige
svar: ved latest klassificeres alle kilder, der besvarer samme relation, før
programmet vælger efter tidspunkt.

- relevant: kilden underbygger den efterspurgte oplysning, eventuelt afklaret af kontekst.
- uncertain: kilden giver konkret grund til en forbindelse til den efterspurgte
  relation, men efterlader den uafklaret eller angiver at oplysningen er udeladt.
- irrelevant: kilden bidrager ikke til den efterspurgte oplysning; emneoverlap alene er ikke nok.

Returnér præcis én vurdering per kandidat. Ved relevant skal quote være et kort
uddrag af kandidatens egen content som bærer vurderingen; ellers er quote tom.
Rangér ikke og vælg ikke en vinder. Tidsmæssig udvælgelse sker i programmet og
ændrer ikke en kildes relevans. Kandidatrækkefølgen må ikke påvirke vurderingen.
