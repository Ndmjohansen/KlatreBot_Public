# Vejledning ved værktøjsresultater

## invalid_dates
Ret datoerne til ISO-tidspunkter eller null. Bevar den ønskede person og kanal.

## latest_types
Latest kræver originale beskeder. Brug memory_types=null og bevar person,
kanal og datoer. Brug relevance hvis seneste forekomst ikke efterspørges.

## source_review
Kontrollér relevans og afsender i originalkilderne. Et begrænset søgeresultat
må ikke fremstilles som en udtømmende undersøgelse af historikken.

## latest_author
Latest kræver en bestemt afsender og person_role=author. Brug relevance til
andre historiske opslag; gæt ikke en person for at udfylde et filter.
