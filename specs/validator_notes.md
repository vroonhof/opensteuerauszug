# Peculiarties of the Verifier 

#### Verifier used
We aim to pass the official verifier tool from the [EWV](https://www.ewv-ete.ch/de/ewv-ete/). 
It is in a helper library that the Technische Wegleitung from the standard refers too as available under an open licence, but has since been unpublished.

[Inquiring minds](https://github.com/vroonhof/opensteuerauszug/issues/68) however have figured out that the JAR is included unchanged in a lot of tax software.

## Adaptions to please the verifier

The verifier has a few quircks

### XML header test

Its test for the presence of the encoding in the XML content type declaration insists on using double quotes despite both type of quotes being alloed in the spec. A bit of massaging of the lxml output is required.

### Tax Statement ID

The verifier insists on format documented in the older 2.1 version of the standard
```
3.2 ID als schweizweit eindeutige Kennung erstellen
Das Attribut ID im Element taxStatement ist für die schweizweit eindeutige ID des E-Steuerauszugs zu verwenden. Die ID setzt sich wie folgt zusammen:

Länderkürzel (2-stellig, alphanumerisch, immer CH)
Clearingnummer des Finanzinstituts (5-stellig, numerisch, mit führenden Nullen)
Stammnummer des Kunden (14-stellig, alphanumerisch, mit führenden Nullen)
Stichtag im Steuerjahr (8-stellig, JJJJMMTT, normalerweise JJJJ1231 für 31.12.)
Laufende Nummer zum Stichtag (2-stellig, beginnend bei 01, mit führenden Nullen)
```
This version is more prescriptive and lets us less room to avoid pretending to be a bank
than the 35 character version allowed in V2.2

We will use
   * The 31 character version described above
   * Fake clearing number as already generated for the 2D barcodes
   * try and squeeze in as much of the normalized import name in front of the account number in the 'stammnummer' slot (it looks like we can keep our solution of postfixing with Xes to pad.)

