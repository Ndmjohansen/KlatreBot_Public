# Kontrollér hele udkastet

Læs originalkilder og kontekst selvstændigt før udkastet vurderes. Beskriv i
source_reading på højst 80 ord hvad de fastslår og hvilke materielle alternative
læsninger de giver grund til. Udkastets formulering og assessment.status er ikke bevis.

Kontrollér at hver claim besvarer spørgsmålet og understøttes af sine citationer,
inklusive afsender, pronomener, tid, forbehold, deltagere og årsagsforhold. Accepter
trofaste parafraser og almindelig indirekte tale; kræv ikke ordrette formuleringer
i svarprosaen. Afvis ændret betydning, opdigtede forhold, fortiet modbevis og
sikkerhed der overstiger kilderne. Opfind heller ikke alternative læsninger uden
grundlag i sproget eller samtalen.

Svaret skal være naturlig dansk prosa frem for en udskrift af kildeuddrag eller
interne handles. Ved latest_selection skal den valgte kilde bære svaret.
Programmets tidsmæssige udvælgelse er gyldigt belæg når uncertain=false; ved
uncertain=true må svaret ikke hævde en sikker seneste forekomst.

Returnér én supported_claims-bool per claim i rækkefølge. valid kræver at alle
claims og helheden består. Ved afvisning skal feedback angive den konkrete fejl
og en understøttet rettelse som stadig besvarer spørgsmålet. Ellers er feedback tom.
