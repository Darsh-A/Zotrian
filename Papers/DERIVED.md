---
title: How Many Elements Matter?
authors: ["Yuan-Sen Ting", "David H. Weinberg"]
year: 2022
doi: 10.3847/1538-4357/ac5023
citekey: DERIVED
paper_type: journalArticle
tags: ["Astrophysics - Astrophysics of Galaxies", "Astrophysics - Solar and Stellar Astrophysics"]
---

# How Many Elements Matter?

## Abstract

Some studies of stars’ multi-element abundance distributions suggest at least 5-7 signiﬁcant dimensions, but others show that many elemental abundances can be predicted to high accuracy from [Fe/H] and [Mg/Fe] (or [Fe/H] and age) alone. We show that both propositions can be, and are, simultaneously true. We adopt a machine learning technique known as normalizing ﬂow to reconstruct the probability distribution of Milky Way disk stars in the space of 15 elemental abundances measured by APOGEE. Conditioning on Teﬀ and log g minimizes the differential systematics. After further conditioning on [Fe/H] and [Mg/Fe], the residual scatter for most abundances is σ[X/H] . 0.02 dex, consistent with APOGEE’s reported statistical uncertainties of ∼ 0.01−0.015 dex and intrinsic scatter of 0.01−0.02 dex. Despite the small scatter, residual abundances display clear correlations between elements, which we show are too large to be explained by measurement uncertainties or by the ﬁnite sampling noise. We must condition on at least seven elements to reduce correlations to a level consistent with observational uncertainties. Our results demonstrate that cross-element correlations are a much more sensitive probe of hidden structure than dispersion, and they can be measured precisely in a large sample even if star-by-star measurement noise is comparable to the intrinsic scatter. We conclude that many elements have an independent story to tell, even for the “mundane” disk stars and elements produced by core-collapse and Type Ia supernovae. The only way to learn these lessons is to measure the abundances directly, and not merely infer them.

## Thesis Notes
### 2 Variance, correlation, and dimensionality

$$
σ′2  k = σ2  k(1 − ρ2  1k).
$$

*(p. 3)*

Here we have used the fact that the variance of χ2n−1 = 2(n − 1).

*(p. 3)*

### 2.1 Revealing abundance dimensionality through dispersion is challenging

While measuring the reduction of variance can be challenging,

*(p. 4)*

### 2.2 Detecting non-zero correlations directly is easier than detecting reductions in dispersions

> [!danger]
> Thus, the measured correlations are always smaller in magnitude than the intrinsic correlations, by a factor that depends on the ratio of observational variance to intrinsic variance
>
> *(p. 5)*

### 3 Describing Distributions with Normalizing Flows

> [!danger]
> Roughly, a Neural Spline Flow performs an invertible spline transformation whose Jacobian is analytically calculable.
>
> *(p. 7)*

> To demonstrate the power of normalizing flow, in Fig. 2, we present a case study with a simple double moon-shaped distribution
>
> *(p. 8)*

> We select Milky Way disk stars from APOGEE DR16 with the following selection criteria
>
> *(p. 9)*

### 4 How many elements matter?

Instead of the usual change of variable, characterized by a neural network

*(p. 9)*

The log g range selects luminous giants, allowing us to sample the full range of Galactocentric radii. The lower Teff cut eliminates cool stars for which ASPCAP abundances may be less reliable

*(p. 10)*

> [!danger]
> with the most reliable abundances. We relax this threshold at low [Mg/H]
>
> *(p. 10)*

### General Notes

have obtained highresolution, high signal-to-noise ratio (SNR) spectra of hundreds of thousands of stars

*(p. 1)*

> This is further complemented by the lower resolution surveys which measure bulk metallicity and other abundance ratios (Ting et al. 2017b; Xiang et al. 2019; Wheeler et al. 2020).
>
> *(p. 1)*

It has long been recognized that the ratio of α-elements (produced mainly by core-collapse supernovae) to iron peak elements (which are additionally produced by SNIa on a longer timescale)

*(p. 1)*

---

## Open Questions

## Connections To Other Papers

## Thesis Relevance
