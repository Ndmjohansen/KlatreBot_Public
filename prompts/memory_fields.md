# Beskrivelser til værktøjer og schemas

## recall
Søg i originale chatbeskeder og afledte minder. Resultater er kandidater;
kontrollér originalkilder før du fremsætter historiske påstande.

## query
Kort semantisk søgetekst. Personer og beskedernes tidsrum angives i filtre.

## reformulation
En anden kort søgeformulering med samme betydning og filtre; opfind ikke svardetaljer.

## channel_id
Kanalens ID. Null bruger den aktuelle kanal.

## people
Kendte Discord-ID'er for efterspurgte personer. Brug enten people eller people_names;
null hvis afsenderen ikke er angivet. Gæt ikke identiteter.

## people_names
Efterspurgte personers navne, aliaser eller præcise Discord-mentions. Null hvis
ingen person er angivet. Bevar personerne ved omsøgning medmindre brugeren retter målet.

## date_start
Inklusivt ISO-tidspunkt for beskedernes afsendelse. Null når ikke afgrænset;
opfind ikke et år eller forveksl afsendelsestid med en omtalt begivenheds dato.

## date_end
Eksklusivt ISO-tidspunkt for beskedernes afsendelse. Null når ikke afgrænset.

## authored_month
Kopiér et udtrykkeligt månedsnavn og eventuelt år der afgrænser afsendelsestid,
også når date_start/date_end er null. Null når måneden kun vedrører et omtalt
emne eller når spørgsmålet i stedet afgrænser før/efter en bestemt dato.

## memory_types
Normalt null for at søge både originalbeskeder og afledte minder. Brug kun et
dokumenttypefilter når det efterspørges. Latest kræver null eller raw_message.

## limit
Maksimalt antal kandidater; null giver 10.

## order
Null/relevance til almindelige historiske opslag. Latest kun ved udtrykkeligt
seneste forekomst fra en bestemt afsender; opslaget fortsætter bagud via cursor.

## person_role
Null/author til personens egne udsagn. Subject til andres udsagn om personen.
Latest kræver author. Et omtalt emne er ikke automatisk et personfilter.

## cursor
Null i første søgning. Brug continuation_cursor med uændrede filtre for at
fortsætte et latest-opslag; ændring af datoer alene fortsætter ikke cursoren.

## sources
Hent originale kildebeskeder og nabokontekst. Bevar hver beskeds afsender;
kontekst kan afklare betydning, men er ikke den primære afsenders egne ord.

## context_radius
Antal nabobeskeder; null giver fem, og 0 giver kun de direkte kilder.
