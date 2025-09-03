# Implementation Notes and Issues

Note: This were created post-hoc from memory so are likely incomplete.

## Issues with the ES-0196 format and work arounds chosen.

### Authority is assumed. 

#### Are we supplying proof of tax withholding?

The E-Steuerauszug contains enough data to fill out the DA-1 form and this in fact happens both in the electronic version and for old "paper" Steuerauszug. The software could cross check Kursliste withholding values against the withholding in the statements, but would the federal bureau processing DA-1's accept that?

###$ Some calculation is always required

There is no real clean way for the software to really just provide the minimal data (position changes, balances, interest). Though some parts make provisions for potentially missing tax data, totals etc are mandatory. Moreover these totals are valuations in CHF, making at least some currency conversion and end of year valuations mandatory.

### Identifiers and other fields assume (swiss) banks

The standard often specifies formats for unique identifiers without making provisos for foreign institutions nor specifying that the client should treat it as an opaque string. e.g.

* The small 1D barcodes that make the PDF a scancenter compatible Steuerauszug consists of fixed digit pattern where one of the parts is the Bankleitzahl/BIC to "guarantee uniqueness". However the space is already fully allocated with swiss banks. We currently squat the space of Swiss National bank and use a 3-digit hash of the broker name.
* A unique customer and unique report ID is required where the format assumes an ID for the financial institution and unique identifier (e.g. customer reference) within that range. As we are neither we prefix the institution ID with "OPNAUS".

There is no real reason for the reader to do anything with these strings (and in fact it is unsafe if it just assumed uniqueness) so hopefully this doesn't actually matter.

### There is no easy way to tell we just using broker data, but are not the broker.

The Schema contains identifying information about the `Organization` managing the securities. Luckily most of it is optional, so we compromise:

   * We provide the name of the broker as text.
   * We omit any formal legal identifiers as we do not want to claim to represent the actual entity.

It is unclear if this causes any downstream issues. 

### Position amounts are implicitly at the start of day

The data schema contains `SecurityStock` assertions about amounts stock held on a given day. Due to how the format works, these must be *at the start* of the day, but this highly unusual in bank statements (and in fact easily confuses our AI code contributors). I cannot find any explicit statement of this fact and sadly don't have a case where I traded a stock on a day of a dividend to see what others do.

### The meaning of the withheld tax fields in unclear

For a foreign investor with a W8-BEN in place at a US institution, the 15% of the tax that is recoverable from the USA under the tax treaty is in fact never withheld. However the data as represented in the XML forces specifying total withholding and the percentages imported from the Kursliste always assume 30% withholding. These values are not rendered in the standard text part and are not necessary for tax computation (unless trying to handle missing W8-BEN and/or failed recovery) so hopefully this does not matter in practice.

## No access to the standardized PDF template

There is a recommended template for the human readable version of the statement. Unfortunately it seems infeasible to get access to more than a blurry JPG for mere mortals. To minimize surprise to the tax office we attempt a best effort approximation based on the real world examples of tax statements the author has.

## Edge cases in calculations

The software tries to delegate tax decisions to the Kursliste or avoid making them, but sometimes they cannot be avoided. This give rise to edge cases that it is hard to get clarification on or suddenly require triple checking what the issuing institute does. The author often is the fortunate situations to not run into these in practice.

* Tax withholding does not apply for amounts under CHF200. For paper statements banks just give totals but it is not clear 100% what happens if there intra-year amounts are below 200. 
* Rounding rules are different for small values (using one more significant digit) arising to a similar problem. In my samples from other banks this is handled very inconsistently.

All of these will likely have negligible effect on the actual tax due. 

