# Vurdér det samlede belæg

Returnér en status og de citationer der er nødvendige for vurderingen:

- supported kræver primært belæg med rollen support.
- contradicted kræver primært modbevis med rollen counterevidence.
- conflicting kræver støtte og modbevis fra forskellige primære kilder.
- uncertain bruges når relevante oplysninger ikke giver et sikkert svar.
- not_found bruges uden citationer når ingen kilde bærer svaret.

Support og counterevidence må kun komme fra sources. Leveret kontekst kan citeres
med rollen context. Et andet emne eller en anden begivenhed er ikke modbevis.
Ved validation_feedback: vurder samme materiale igen og ret den angivne fejl.
