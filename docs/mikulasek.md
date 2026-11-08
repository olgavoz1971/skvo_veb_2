# Phenomenological modelling of eclipsing system light curves

Zdeněk Mikulášek

Department of Theoretical Physics and Astrophysics, Masaryk University, Kotlářská 2, CZ 611 37, Brno, Czech Republic

e-mail: mikulas@physics.muni.cz

Received / Accepted

## Abstract

**Context.** The observed light curves of most eclipsing binaries and stars with transiting planets can be well described and interpreted by current advanced physical models which also allow for the determination of many physical parameters of eclipsing systems. However, for several common practical tasks there is no need to know the detailed physics of a variable star, but only the shapes of their light curves or other phase curves.

**Aims.** We present a set of phenomenological models for the light curves of eclipsing systems.

**Methods.** We express the observed light curves of eclipsing binaries and stars, transited by their exoplanets orbiting in circular trajectories, by a sum of special, analytical, few-parameter functions that enable fitting their light curves with an accuracy of better than 1%. The proposed set of phenomenological models of eclipsing variable light curves were then tested on several real systems. For XY Bootis, we also compare in details the results obtained using our phenomenological modelling with those found using available physical models.

**Results.** We demonstrate that the proposed phenomenological models of transiting exoplanet and eclipsing binary light curves applied to ground-based photometric observations yields results compatible with those obtained by the application of more complex physical models.

**Conclusions.** The suggested phenomenological modelling appears useful to solve a number of common tasks in the field of eclipsing variable research.

**Key words.** stars: variables – stars: eclipsing: – exoplanets

## 1. Introduction

There are two groups of astrophysical tasks standardly solved by the analysis of observations of eclipsing binaries (EBs) and stars with transiting extrasolar planets. We can derive the physics of the present state of a system and its components -– namely the dimensions and geometry of the system, outer characteristics of both eclipsing bodies such as their radii, shapes, masses, temperatures, limb darkening, gravity darkening/brightening, gravitational lensing, albedos, spottiness, pulsation, and parameters of possible streams and disks. Required information is extracted by means of various, more or less sophisticated physical models of double systems (e.g. Wilson & Devinney 1971; Kallrath & Milone 1998; Hadrava 2004; Bradstreet 2005; Prša & Zwitter 2005; Prša et al. 2011; Pribulla 2012) applied to numerous and precise data of all kinds obtained by contemporary observational methods and approaches developed for this purpose.

Equally important are the description and classification of light curves (LCs), or studies of the evolution of the systems, within the time scale of decades. These usually very tiny changes in light variation parameters (typically the period) may provide information on e.g. the rate of mass exchange between interacting components (e.g. Zhu et al. 2010, 2012; Mikulášek et al. 2012a), the presence and characteristics of possible invisible bodies (stars, planets, e.g. Van Hamme & Wilson 2007; Qian et al. 2005) in the system, or the degree of the mass concentration in stellar interiors (internal structure constants) if we study apsidal motion in some eccentric EBs (e.g. Kopal 1978; Claret & Gimenénez 1993; Zasche & Wolf 2013), etc.

In period analyses of EBs we do not need all the information about the physics of the system, but only good templates of phase curves of all data we want to analyse (Mikulášek et al. 2012a). Such template phase curves (typically light curves in various photometric bands) can be obtained in principle by means of the sophisticated versions of physical EB models applied to the complete set of observational data (see in Van Hamme & Wilson 2007; Wilson & Van Hamme 2014) or to their best parts (e.g. Zasche et al. 2014; Zasche 2015). There is also the possibility of using the best observed LCs themselves (Pribulla et al. 2012). We offer another alternative using relatively simple phenomenological (mathematical) modelling of observed data variations.

Our aim is to establish a general model of light curves of *eclipsing systems – ES* (both eclipsing binaries and stars with transiting planets) that could fit the LCs with an accuracy of 1% of their amplitudes or better that can be applied to the majority of observed eclipsing systems (the concept of the model is outlined in Mikulášek et al. 2015). Such a model could be used for most LC description tasks and detailed period analysis, for which other sources of phase information could be also used, especially individual eclipse timings and radial-velocity (RV) curves.

The remainder of this paper is organised as follows: in Sect. 2 we describe the general properties of phase variation of periodically variable objects, Sect. 3 specifies general properties of eclipsing system LC models, and Sect. 4 presents the phenomenological model of eclipsing system light curves. Sect. 5 is devoted to model parameters and searching for them during analysis, in Sect. 6 we compare the results of the modelling XY Boo observations processed by means phenomenological and physical (Wilson & Van Hamme 2014) methods, and in Sect. 7 we summarise and discuss our results of the phenomenological modelling of the eclipsing systems.

## 2. Periodically variable objects
<!-- section:gen -->

Eclipsing binaries and stars with transiting exoplanets periodically change their light mainly due to regular mutual eclipses of components (transits and occultations) and proximity effects (tidally induced ellipticity of components and reflection). The period of these ES variations corresponds to the observed orbital velocity of the system; the shape of light curves, dominated by eclipses and proximity effects, is hence more or less constant (for details see Sect. 3). That is why ESs are ranked into a group of periodically variable stars, or objects in general.

Most of the variations of periodic variables are more or less cyclic with an observed *instantaneous period* $P(t)$ which is usually strictly constant or slightly variable. The period itself and its development over time can not be observed directly, but both can be derived through the analysis of time series of light changes or extremum timings. For that purposes it was useful to introduce a monotonically rising *phase function* $\vartheta(t)$, as a sum of the epoch $E(t)$ and the phase in the common usage $\varphi$ and its inversion function $t(\vartheta)$ (Mikulášek et al. 2008).

Functions $\vartheta(t)$ are tied with the instantaneous observed period $P(t),\,P(\vartheta)$ by the following differential equations (see Kalimeris et al. 1994; Mikulášek et al. 2008, 2012b):

$$
\frac{\mathrm{d}\vartheta(t)}{\mathrm{d}t}=\frac{1}{P(t)}, \vartheta(M_0)=0;\quad \frac{\mathrm{d}t(\vartheta)}{\mathrm{d}\vartheta}=P(\vartheta); t(0)=M_0,
\tag{1}
$$
<!-- equation phasefundef -->

where $M_0$ is the origin of counting of epochs (for ESs the time of the basic primary minimum).

Using $t(\vartheta)$ we can predict the zeroth phase time $\mathit{\Theta(E)}$ for the epoch $E$ (primary minimum timing according to the ephemeris Eq. (1)), $\mathit{\Theta(E)}=\mathit{\Theta}(\vartheta=E)$.

### 2.1. Period models. Phase and time shifts.
<!-- section:phase -->

The linear period model supposes the period $P(t)$ of the variable object to be constant. The corresponding linear phase function $\vartheta_1(t,M_0,P_0)$ and its inversion $t_1(\vartheta,M_0,P_0)$ are then given by:

$$
\vartheta_1(t)=(t-M_0)/P_0,\quad t_1(\vartheta)=M_0+P_0\,\vartheta.
\tag{2}
$$
<!-- equation linmod -->

A possible tiny modulation $\Delta P(t)$ of the basic period $P_0$ causes a detectable phase function shift $\Delta \vartheta(t)$ in light curves and shifts $\Delta t(\vartheta)=\Delta \mathit{\Theta}(E)$ in LC extrema timing.

$$
P(t)=P_0+ \Delta P(t); \vartheta(t)=\vartheta_1+\Delta \varphi (t); \ t(\vartheta)=t_1+\Delta t(\vartheta).
\tag{3}
$$
<!-- equation shifts -->

Combining definitions in Eq. 3 with the fact that functions $\vartheta(t)$ and $t(\vartheta)$ are mutually inverse, we obtain the following relations

$$
\begin{aligned}
&\Delta t = -P_0\,\Delta\vartheta; \quad \Delta P(\vartheta)=\frac{\mathrm d \Delta t(\vartheta)}{\mathrm d \vartheta}=\frac{\mathrm d \left[t(\vartheta)-t_1(\vartheta)\right]}{\mathrm d \vartheta};
\end{aligned}
\tag{4}
$$
<!-- equation relat -->

$$
\begin{aligned}
&\Delta \vartheta(t)\doteq\int_{M_0}^t \left[\frac{\Delta P(\tau)}{P_0^2} -\frac{\left(\Delta P(\tau)\right)^2}{P_0^3}\right]\,\mathrm{d}\tau \doteq \int_{M_0}^t \frac{\Delta P(\tau)}{P_0^2}\,\mathrm{d}\tau.
\end{aligned}
\tag{5}
$$
<!-- equation deltafi -->

The last approximation in the Eq. (5) is valid for all known EBs, including SV Cen with a record-breaking decrease of its orbital period by $\dot{P}/P_0=-2.36(5)\times10^{-5}$ yr$^{-1}$ (Drechsel et al. 1982).

The time development of phase function shifts $\Delta \vartheta(t)$ can be derived by the analysis of light curves, whilst $\Delta \mathit {\Theta}(E)$, can be revealed using standard *O-C* diagrams constructed by means of extrema timings.

### 2.2. Basic period models. Finding of *O-C* shifts
<!-- section:permods -->

If the time development of the period $P(t)$ is continuous and smooth we can express it in the form of the Taylor polynomial with the centre at $t=M_0$, $\vartheta_1=(t-M_0)/P_0$

$$
P(t)=P_0+P_0\dot{P}_0\,\vartheta_1 +P_0^2\ddot{P_0}\frac{\vartheta_1^2}{2!}+\ldots+ P_0^k \frac{\mathrm d^k\!P_0}{\mathrm dt^k}\frac{\vartheta_1^k}{k!}\ldots
\tag{6}
$$
<!-- equation perlaurin -->

Using Eqs. (2), (3), (4), and simplified version of Eq. (5) we obtain:

$$
\begin{aligned}
\vartheta&\simeq\vartheta_1 -\dot{P_0}\,\frac{\vartheta_1^2}{2!}- P_0\ddot{P}_0\,\frac{\vartheta_1^3}{3!}-\ldots - P_0^{k-1} \frac{\mathrm d^k\!P_0}{\mathrm dt^k}\frac{\vartheta_1^{k+1}}{(k+1)!}\ldots
\end{aligned}
\tag{7}
$$
<!-- equation thetalaurin -->

$$
\begin{aligned}
t&\simeq M_0\!+\!P_0\,\vartheta+P_0\dot{P}_0\frac{\vartheta^2}{2!}\!+\! P_0^2\ddot{P}_0\frac{\vartheta^3}{3!}\!+\!\ldots\!+\!P_0^k \frac{\mathrm d^k\!P_0}{\mathrm dt^k}\frac{\vartheta^{k+1}}{(k+1)!}\ldots
\end{aligned}
$$
<!-- unnumbered line in the source (\nonumber) -->

$$
\begin{aligned}
\mathit\Theta&\simeq M_0\!+\!P_0\,E+P_0\dot{P}_0\frac{E^2}{2!}\!+\! P_0^2\ddot{P}_0\frac{E^3}{3!}\!+\!\ldots\!+\!P_0^k \frac{\mathrm d^k\!P_0}{\mathrm dt^k}\frac{E^{k+1}}{(k+1)!}\ldots
\end{aligned}
\tag{8}
$$
<!-- equation Thetalaurin -->

Similarly we can establish other arbitrarily complex period models of $\vartheta(t)$ determined by a set of free parameters including also cyclic period modulation of the light time effect (LiTE) caused by another body in the system (Mikulášek et al. 2011b; Liška et al. 2015) or the apsidal motion.

The real shape of the phase curve can also be approximated using so-called *O-C* time shifts of the observed phase curves versus the predicted light curve (LC) derived by the period model with fixed parameters (typically $P_0,M_0$) expressed in time units (usually in days). Let us divide the whole time interval covered by observations into $n_{\mathrm{OC}}$ appropriate time intervals (typically nights or seasons). The phase function $\vartheta(t,r)$ during a certain $r$-th time interval with the $(\textit{O-C})_r$ time shift is then given by the formula (Mikulášek et al. 2011a)

$$
\vartheta(t,r,\vartheta_{\mathrm c},\{\textit{O-C}\})=\vartheta_{\mathrm c}(t) - \sum_{s=1}^{n_{\mathrm{OC}}} \,\eta_{rs}\,\frac{(\textit{O-C})_s}{P},
\tag{9}
$$
<!-- equation oc -->

where $\vartheta_{\mathrm c}(t_i)$ is a predicted phase function calculated by an appropriate period model at the time $t_i$, $\{\textit{O-C}\}$ is a set of all $n_{\mathrm{OC}}$ values of the found $(\textit{O-C})_r$ time shifts versus this model. The symbol $\eta_{rs}$ represents a discrete function (a table or a matrix), which for each individual $i$-th observation from our data assigns either 1, if its order number of the interval $r_i=s$, or 0, if $r_i\neq s$.

The dependence of *O-C* values on the epoch serves as a common *O-C* diagram, the basic tool for the period analysis. Using the found individual *O-C* values and their uncertainties we can calculate a set of so-called virtual minima timings (Mikulášek et al. 2011a, 2011b, or Sect. 6.4.2 in this paper). Virtual minima timings can be combined with others derived e.g. by other techniques (e.g. Brát et al. 2012; Mandel & Agol 2002; Kwee & van Woerden 1956; Mikulášek et al. 2006, 2014; Zasche et al. 2014; Zasche 2015).

## 3. General properties of an eclipsing system light curve model
<!-- section:zero -->

### 3.1. Instrumental term of an observed light curve
<!-- section:instrum -->

The observed light curve (or its segment) of a chosen eclipsing system in a particular colour of an effective wavelength $\lambda_{\mathrm{eff}}$ is defined by a time series $\{t_{ri},y_{ri}\}$ obtained during an observational interval $r$ (observing night, part of it or season). The $r$-th subset of observational data can be generally modelled by the function $Y_r(t,\lambda_{\mathrm{eff}})$, expressed in magnitudes[^1]:

$$
Y_r(t,\lambda_{\mathrm{eff}})=Y_{0r}(t,\lambda_{\mathrm{eff}})+F(\vartheta,\lambda_{\mathrm{eff}});
\tag{10}
$$
<!-- equation general -->

where $Y_{0r}(t,\lambda_{\mathrm{eff}})$ is an additive term removing instrumental trends and concurring the observed magnitudes or magnitude differences $\{y_i\}$, whilst $F(\vartheta,\lambda_{\mathrm{eff}})$ is an intrinsic light curve model function of the phase function $\vartheta$ (see Sect. 2.1) and the effective wavelength $\lambda_{\mathrm{eff}}$, free of instrumental and observational shifts and trends. The function $F(\vartheta,\lambda_{\mathrm{eff}})$ is normalized so that its mean value without eclipses is equal to zero. The function $Y_{0r}(t,\lambda_{\mathrm{eff}})$ can be approximated by a linear combination of $g_r$ dimensionless functions of time $t$, $\mathit{\Xi}_j\,(t)$, with magnitude-like coefficients $m_{0rj}(\lambda_{\mathrm{eff}})$:

$$
Y_{0r}(t,\lambda_{\mathrm{eff}})\simeq \sum_{j=0}^{g_r} \,m_{0rj}\,(\lambda_{\mathrm{eff}}) \mathit{\Xi}_{j}\,(t),
\tag{11}
$$
<!-- equation instrument -->

where $\mathit{\Xi}_j\,(t)$ can be e.g. normalised polynomials $\mathit{\Xi}_{rj}\,(t)=[(t-\bar{t_r})/\sigma(t_r)]^j$ ($\sigma(t_r)$ is the weighted variance of observational times in the segment $r$) or Legendre polynomials or special quasi orthogonal functions combining polynomials with harmonic functions (see in Mikulášek & Gráf 2005). The set of coefficients $\{m_{0rj}\,(\lambda_{\mathrm{eff}})\}$ is found together with parameters describing the model function $F(\vartheta,\lambda_{\mathrm{eff}})$.

### 3.2. Bases and limitations of the phenomenological model of eclipsing system light curves
<!-- section:bases -->

Light curves of ESs are nearly periodic functions and it would be natural to express them in the form of Fourier series (see e.g. Rucinski 1973; Kallrath & Milone 1998; Selam 2004; Nedoroščík et al. 2012; Andronov 2012). This concept proves its worth in many types of extrinsic periodically variable stars, especially in the case of rotating variables with photometric spots on their surfaces (North 1984; Mikulášek et al. 2007) or non-eclipsing (e.g. purely elliptical) double stars, where we manage with harmonic polynomials of a low degree (e.g. Kallrath & Milone 1998).

However, it is generally known that the presence of eclipses in LCs asks for the use of harmonic polynomials of a rather high degree if a proper fit of the observed LC is required. Their usage is badly influenced by departures from the ideal equidistant distribution of observations according to the orbital phase. Even small phase gaps are then filled with unreal LC artifacts.

It seems that it is better to use properly selected phenomenological models of LCs of eclipsing systems described by a few parameters. Several more or less successful attempts on how to model these LCs have been proposed e.g. by Tsesevich (1971); Kholopov (1981), see also the reviews and references in Andronov (2012); Chrastina et al. (2013), Table 2, and Fig. 1, 9.

Theory is able to explain the observed periodic light variations of an ES in general and in detail as the result of alternating mutual eclipses of components of the system, non-isotropic radiation of orbiting components, caused by their close proximity, and by unevenly distributed photometric spots on rotating components (e.g. Bradstreet 2005; Hilditch 2001; Pribulla et al. 2012). The periodicity of light changes caused by mutual eclipses and proximity effects, as well as variations connected with the rotation of synchronously rotating spotted components is dictated by their observed orbital motion. These changes are periodic with an instantaneous period[^2] $P(t)$, the shapes of light curves remain more or less constant for decades.

For purely geometrical reasons the prevailing majority of EBs ranks among relatively close, and hence tidally interacting systems, where the processes of synchronizing of the components'rotation and orbit circularization are strong and effective (Zahn 1992; Goldman & Mazeh 1991, and references therein). That is why the rotations of components are usually synchronous and more than 80 % of their orbits are pretty circular (see CALEB, Bradstreet 2005). In the further introductory text we will concentrate mainly on systems with more or less circular orbits[^3] and constant light curves[^4].

The intrinsic one-colour light curve function (expressed in magnitudes) of an eclipsing system is a periodic function $F(\vartheta,\lambda_{\mathrm{eff}})$ that can be approximated as the sum of three more or less independent terms (see also in Andronov 2012):

$$
F(\vartheta,\lambda_{\mathrm{eff}})=F_{\mathrm e}(\vartheta,\lambda_{\mathrm{eff}})+F_{\mathrm p}(\vartheta,\lambda_{\mathrm{eff}})+F_{\mathrm c}(\vartheta,\lambda_{\mathrm{eff}}),
\tag{12}
$$
<!-- equation EBbas -->

where $F_{\mathrm{e}}(\vartheta,\lambda_{\mathrm{eff}})$ describes a light curve of eclipses ($F_{\mathrm{e}}\equiv 0$ outside of eclipses), whilst $F_{\mathrm{p}}(\vartheta,\lambda_{\mathrm{eff}})$ and $F_{\mathrm{c}}(\vartheta,\lambda_{\mathrm{eff}})$ express contributions of proximity and O'Connell (1979) effects without eclipses ($\overline{F_{\mathrm p}}=\overline{F_{\mathrm c}}=0$). The mathematical models are formulated and discussed in Sect. 4.1.2.

**Figure 1.** Examples of elementary model LC $\mathit{\Psi}=F_{\mathrm e}/A_k$, for $C=0$, see Eq. (13) allowed by our phenomenological EB models. Parameter $d$ describes the duration of the eclipse, $\mathit{\Gamma}$ is a parameter expressing the kurtosis of the LC.

<!-- figure:cecka file:fig1.eps -->

*[manual review: graphic not embedded; source file `fig1.eps`.]*

## 4. Phenomenological model of eclipsing system light curves
<!-- section:fenec -->

### 4.1. Model of one-colour light curves
<!-- section:monmodel -->

#### 4.1.1. Eclipses
<!-- section:monec -->

The essential feature of all ES light curves are two nearly symmetrical depressions caused by mutual eclipses of synchronously rotating stellar or planetary components. The profiles of both minima are complex functions determined primarily by the geometry of the system and the relative brightness of components in a given spectral region centered at the effective wavelength $\lambda_{\mathrm{eff}}$. The contribution of eclipses $F_{\mathrm{e}}(\vartheta,\lambda_{\mathrm{eff}})$ to an ES light curve can be approximated by a sum of two special periodic functions of phase function $\vartheta$. In the case of circular orbits eclipses are exactly symmetrical around their centres at phases $\varphi_{01}$ and $\varphi_{02}$. If we put the origin of the phase function $M_0$ at the time of the primary minimum, then $\varphi_{01}=0, \varphi_{02}=0.5$.

The model function was selected so that it describes as aptly as possible those parts of LCs that are in the vicinity of their inflex points, where their slopes are maximal. The functions are parameterised by their widths $D_1,\,D_2$, eclipse LC kurtosis coefficients $\mathit{\Gamma}_1,\,\mathit{\Gamma}_2$, dimensionless correcting factors $C_1, C_2$, and central depths $A_1(\mathit{\lambda_{\mathrm{eff}}}),\, A_2(\mathit{\lambda_{\mathrm{eff}}})$:

$$
\begin{aligned}
& F_{\!\mathrm{e}}(\vartheta,\!\lambda_{\mathrm{eff}})=\! \sum_{k=1}^{n_{\mathrm{e}}}\!A_{k}\left(1\!+\!C_{\!k}\!\frac{\varphi_k^2}{D_k^2}\right) \left\{1\!-\!\left\{1\!-\!\exp\!\left[1\!-\!\cosh\!\left(\frac{\varphi_k}{D_k}\right)\right] \right\}^{\mathit{\Gamma\!_k}}\right\}, \\
&\varphi_k=\vartheta-0.5\,(k-1) -\mathrm{round}\left[\vartheta-0.5\,(k-1)\right],
\end{aligned}
\tag{13}
$$
<!-- equation modelecl -->

where the summation is over the number of eclipses during one cycle, $n_{\mathrm e}$: $n_{\mathrm e}=2$ or $n_{\mathrm e}=1$ (the common situation for exoplanet transits). Each eclipse in a given colour is thus described by only four parameters - its depth $A$, width $D$, kurtosis $\mathit{\Gamma}$, and the correcting parameter $C$.

**Figure 2.** The fit of the $V$ curve of the overcontact spotted EB EK Com (the secondary minimum is a transit). The LC of the close binary is affected by O'Connell and proximity effects. The synthetic model curve is depicted by a solid line, the phenomenological LC fit is depicted by the dashed line. For more information see Sect. 4.3 and Table 1.

<!-- figure:ekcom file:fig2.eps -->

*[manual review: graphic not embedded; source file `fig2.eps`.]*

In the case of eclipsing binaries with two minima in a cycle ($n_{\mathrm e}\!=\!2$) we need eight parameters, but sometimes the number of needed parameters can be smaller. Inspecting the parameters $D, \mathit{\Gamma}$, and $C$ for both eclipses of many EBs we have concluded that they are as a rule nearly the same: especially $D_1\!\cong\!D_2, \mathit{\Gamma}_1\!\cong\!\mathit{\Gamma}_2$, and $C_1\!\cong\! C_2$. So we usually need only five monochromatic parameters ($A_1,A_2,D,\mathit{\Gamma},C$). The parameter $C$ is mostly comparable with its uncertainty, so we can neglect it entirely. Then we need just four parameters! On the other hand, in EBs with totalities we see that the bottoms of their occultations are flat whilst transits are convex. It can be described by introducing of different parameters $C_1, C_2$ (see the case of EK Com in Table 1, Fig. 2).

The LCs of the exoplanet transits ($n_{\mathrm e}=1$) need only four parameters ($A,D,\mathit{\Gamma},C$ - see Fig. 3), in cases of very precise measurements we add another dimensionless parameter $K$ (Mikulášek et al. 2015):

$$
F_{\!\mathrm{e}}=A\left(1\!+\!C\frac{\varphi^2}{D^2}\!+ \!K\frac{\varphi^4}{D^4}\right) \left\{1\!-\!\left\{1\!-\!\exp\left[1\!-\!\cosh\left(\frac{\varphi}{D}\right)\right] \right\}^{\mathit{\Gamma}}\right\}.
\tag{14}
$$
<!-- equation modeltrs -->

Testing several dozens of LCs of various types of eclipsing systems we found that the standard deviation of the fit is typically well bellow one per cent. The only minor inconvenience is the existence of a spike (a jump in derivatives) in the mid-eclipses for LCs with $\mathit{\Gamma}<1$ (see Fig. 1).

**Figure 3.** The simultaneous fit to 15 transits of extrasolar planet TrES-3b corrected for trends (see Eq. (10)). The fit parameters according to Eq. (14): $A=0.02725(19)$ mag, $D=0.0117(7)$, $C=-0.17(7)$, and $\mathit{\Gamma}=1.58(12)$, the parameter $K$ was not introduced. The black line is the fit, circles are the normal points, grey circles indicate individual measurements with the area proportional to their weights.

<!-- figure:tres3 file:fig3.eps -->

*[manual review: graphic not embedded; source file `fig3.eps`.]*

#### 4.1.2. Proximity effects. O'Connell effect
<!-- section:proxicon -->

Light variations of EBs caused by eclipses are usually modified by asphericity of the components, effects of gravity darkening/brightening and mutual irradiation. All these *proximity effects* are the manifestation of the interaction between the components acting, namely, in close systems. Contrary to eclipses the proximity effects modify LCs permanently, in each phase.

Light curves of some eclipsing binaries are influenced by the O'Connell effect that results in the asymmetry of some LCs of close EBs, manifesting as the difference in light maxima between eclipses. The standard explanation for this is the presence of one or more cool or hot spots on the surface of one of the synchronously rotating components or by asymmetrically distributed circumstellar material in the system (e.g. Wilsey & Beaky 2009; Pribulla et al. 2012, and citations therein). The amount and the sign of the O'Connell effect vary with time (Beaky & Koju 2012). The effect is also wavelength dependent – in blue it is usually stronger, but it is not a rule (Pribulla et al. 2012).

The contribution of proximity effects $F\!_{\mathrm p}(\vartheta)$ should be an even function symmetric with the phases 0.0 and 0.5 and consequently they can be satisfactorily well expressed as a linear combination of $n_{\mathrm p}$ elementary cosine functions $\cos(2\,\pi\,\vartheta),\,\cos(4\,\pi\,\vartheta),\,\cos(6\,\pi\,\vartheta),\ldots$ . The even terms are the consequence of the ellipticity of tidally interacting components, whilst the odd terms result from the differences between the near and far sides of components. As a rule we can limit ourselves only to the first two or three terms in the $F\!_{\mathrm{p}}$ (Russell & Merrill 1952; Kallrath & Milone 1998). The O'Connell effect contribution $F_c(\vartheta)$ can be well modelled by a simple sinusoid (Davidge & Milone 1984; Wilsey & Beaky 2009):

$$
F\!_{\mathrm p} =\!\sum_{k=n_{\mathrm e}+1}^{n_{\mathrm p}+ n_{\mathrm e}}\! A_k\cos\left[2\pi(k\!-n_{\mathrm e})\vartheta\right],\ F\!_{\mathrm c}=\!\sum_{k=n_{\mathrm p}+n_{\mathrm e}+1}^{n_{\mathrm c}+ n_{\mathrm p}+n_{\mathrm e}}\! A_k\sin(2\pi\vartheta),
\tag{15}
$$
<!-- equation proxcon -->

where $n_{\mathrm p}$ is the number of terms in $F\!_{\mathrm p}(\vartheta)$: $n_{\mathrm p}=0,1,2,3,\ldots$, $n_{\mathrm c}=0$, if the O'Connell asymmetry is not present[^5], else $n_{\mathrm c}=1$.

**Table 1.** Parameters describing LCs of several eclipsing binaries.

<!-- table:prm -->

| Name | AR Aur | EK Com | AV Del | 477 Lyr |
| --- | --- | --- | --- | --- |
| $g_{\mathrm{a}}$ | 9 | 10 | 13 | 8 |
| filter | $B/V$ | $V$ | $BVRI$ | $V$ |
| $n$ | 686/687 | 247 | 545 | 294 |
| $D$ | 0.0168(3) | 0.052(3) | 0.0396(7) | 0.0219(5) |
| $\mathit{\Gamma}$ | 0.619(10) | 1.7(4) | 0.82(5) | 0.79(4) |
| $a_{11}$ | 0.691/0.681 | 0.331(12) | 1.153(11) | 1.557(14) |
| $a_{12}$ | – | – | 1.17(4) | – |
| $a_{21}$ | 0.551/0.564 | 0.289(9) | 0.123(3) | 0.078(5) |
| $a_{22}$ | – | – | -0.188(13) | – |
| $a_{31}$ | -0.0022(5) | 0.023(5) | – | 0.321(2) |
| $a_{32}$ | -0.022(4) | – | – | – |
| $a_{41}$ | 0.0028(9) | 0.150(5) | 0.050(2) | -0.035(2) |
| $a_{42}$ | – | – | -0.044(1) | – |
| $a_{51}$ | – | – | – | -0.005(2) |
| $a_{61}$ | – | 0.032(2) | – | – |
| $C$ | -0.25(2) | – | -0.24(7) | -0.342(20) |
| $C_{1}$ | – | 0.10(17) | – | – |
| $C_{2}$ | – | -0.14(9) | – | – |
| $\rho$ | 1.05 | 0.73 | 1.05 | 0.31 |
| type | OC | SD | D | D |
| $P$ | $4.\!\!^{\mathrm{d}}13169$ | $0.\!\!^{\mathrm{d}}26669$ | $3.\!\!^{\mathrm{d}}8534$ | $0.\!\!^{\mathrm{d}}47173$ |
| $r_1$ | 0.098 | 0.524 | 0.198 | 0.077 |
| $r_2$ | 0.100 | 0.318 | 0.343 | 0.219 |
| $T_{\mathrm{eff}1}$ | 11 100 K | 5000 K | 6000 K | 60 000 K |
| $T_{\mathrm{eff}2}$ | 10 600 K | 5300 K | 4275 K | 6500 K |
| $i$ | $88.5^{\circ}$ | $88.5^{\circ}$ | $81.3^{\circ}$ | $65.8^{\circ}$ |
| Fig. | 5 | 2 | 8 | 4 |

$g_{\mathrm{a}}$ is the number of the parameters used for the description of a LC, $\rho=\delta_{\mathrm{phen}}/\delta_{\mathrm{phys}}$, where $\delta_{\mathrm{phen}}$ and $\delta_{\mathrm{phys}}$ are the uncertainties in the determination of the zero phase time according to phenomenological and physical models. The used ‘hi-fi’ LC model: $F(\vartheta,\mathit{\Lambda})=\sum_{k=1}^2\sum_{j=1}^3\,a_{k\!j} \mathit{\Lambda}^{j-1} [1+C_k\,(\varphi_k/D)^2] \{1-\{1-\exp\left[1-\cosh\left(\varphi_k/D\right)\right] \}^{\mathit{\Gamma}}\}$ $+\sum_{k=3}^5\sum_{j=1}^2\,a_{k\!j}\,\mathit{\Lambda}^{j-1} \cos\left[2\,\pi\,(k\!-\!2)\,\vartheta\right]+a_{60}\,\sin(2\,\pi\,\vartheta).$ EB types: OC - overcontact, C - contact, SD - semidetached, D - detached, $P$ is the period, $r_1,r_2$ are the relative radii of the components, $T_{\mathrm{eff}1},T_{\mathrm{eff}2}$, their effective temperature, $i$ is the orbit inclination. The parameters were taken from authors cited in Sect. 4.3.

**Figure 4.** $V$ light curve of a famous EB consisting of a very hot nucleus of a planetary nebula and solar type star. For the fit of the LC strongly affected by proximity effects we need only 8 parameters phenomenological. For details see Sect. 4.3 and Table 1.

<!-- figure:477lyr file:fig4.eps -->

*[manual review: graphic not embedded; source file `fig4.eps`.]*

**Figure 5.** The fit of the primary minimum of the detached EB AR Aur in $V$ and $B$, represented by normal points (circles), by physical (grey solid lines) and phenomenological (dashed lines) LCs (see Table 1).

<!-- figure:arprim file:fig5.eps -->

*[manual review: graphic not embedded; source file `fig5.eps`.]*

The $V$ light curve of the close eclipsing binary EK Com (see Fig. 2) with apparent O'Connell effect is described by nine parameters: $A_{1,2,3,4,5},D,C_{1,2},\mathit{\Gamma}$,  $n_{\mathrm e}=2$, $n_{\mathrm p}=2,\,n_{\mathrm c}=1$. The uncommon $V$ light curve of EB V477 Lyr (see Fig. 4) is determined by eight parameters: $A_{1,2,3,4,5},D,C,\mathit{\Gamma}$, $n_{\mathrm e}=2$, $n_{\mathrm p}=3,\,n_{\mathrm c}=0$.

### 4.2. The model of multicolour light curves
<!-- section:multik -->

The parameters of the above defined model functions, especially the amplitudes $A_k$, and parameters $C_{1,2}$, $D_{1,2}$ and $\mathit{\Gamma_{1,2}}$ are generally functions of the wavelength $\lambda$.

In principle, we can use the one-colour models formulated in Sect. 4.1 separately, assuming that all of the parameters are wavelength dependent. Fortunately, it follows from our experience with modelling of LCs of hundreds of real systems and their physical models that it is not necessary to take response curves of different photometric passbands into account; we manage with their effective wavelengths only. It enables the association of photometric colours with different transparency widths, equal or close effective wavelengths (typically we are allowed to combine measurements done in $V$ and $y$).

**Figure 6.** Ten-colour transit LCs for HD 209458b taken from Knutson et al. (2007). Effective wavelengths of individual colours are in nm. For the description of all 10 light curves we need only 9 parameters (courtessy of Mikulášek et al. 2015)

<!-- figure:knut file:fig6.eps -->

*[manual review: graphic not embedded; source file `fig6.eps`.]*

**Figure 7.** The dependence of the amplitude $A$ of transit of HD 209458b (see Fig. 6) on $\mathit{\Lambda}=550/\lambda_{\mathrm{eff}}-1$ proves the validity of the approximation Eq. (16) for that case.

<!-- figure:ampl file:fig7.eps -->

*[manual review: graphic not embedded; source file `fig7.eps`.]*

On top of that the dependencies of model parameters on the effective wavelength $\lambda_{\mathrm{eff}}$ are typically smooth, mostly monotonic, so we can approximate them by low-order polynomials of the dimensionless parameter $\mathit {\Lambda}$; $\mathit{\Lambda}=\lambda_0/\lambda_{\mathrm {eff}}-1$, where $\lambda_0$ is an arbitrarily selected central wavelength of the data set (Mikulášek et al. 2015, see also Fig. 7):

$$
\begin{aligned}
& A_{k}=\sum_{j=1}^{g_{ {A\,k}}}a_{kj}\,\mathit{\Lambda}^{j-1},\quad C_l=\sum_{j=1}^{g_{C\,l}}c_{lj}\,\mathit{\Lambda}^{j-1}, \\
& D_l=\sum_{j=1}^{g_{D\,l}}d_{lj}\,\mathit{\Lambda}^{j-1},\quad \mathit{\Gamma}_{l}=\sum_{j=1}^{g_{\mathit{\Gamma} l}}\gamma_{lj}\,\mathit{\Lambda}^{j-1},
\end{aligned}
\tag{16}
$$
<!-- equation multi -->

where $g_{Ak}, g_{Cl}, g_{Dl}, g_{\mathit{\Gamma} l}$, $l=1,2$ or $l=1$, are the numbers of degrees of freedom of the corresponding parameters of the model. The standard set of the one-colour LC model parameters of EBs (see Sect. 4.1): $\{A_k,C_l,D_l,\mathit{\Gamma}_l\}$ can be considered as the special case of the multicolour decomposition Eq. (16) for $\lambda_0=\lambda_{\mathrm{eff}}, \mathit{\Lambda}=0$, $j=1$: $\{a_{k1},c_{l1},d_{l1},\mathit{\gamma}_{l1}\}$.

The set of relations in Eq. (16) enables the calculations of all parameters $\{A_k(\mathit{\Lambda}),C_l(\mathit{\Lambda}),D_l(\mathit{\Lambda}), \mathit{\Gamma}\!_l(\mathit{\Lambda})\}$ needed for calculation of the model of a LC in any photometric band characterized by the parameter $\mathit{\Lambda}$.

Fig. 6 shows the fit of the extreme 10-colour photometry (350-980 nm) of an exoplanet transit (Knutson et al. 2007) – here we need 9 parameters, namely $A=a_1+a_2\mathit{\Lambda}$, $D=d_1+d_2\mathit{\Lambda}$, $C=c_1+c_2\mathit{\Lambda}+c_3\mathit{\Lambda}^2$, $\mathit{\Gamma}=\gamma_1+\gamma_2\mathit{\Lambda}$, where $\mathit{\Lambda}=550/\lambda_{\mathrm{eff}} -1$ (Mikulášek et al. 2015).

The fit of *BVR*$_{\mathrm{c}}$*I*$_{\mathrm{c}}$ proper LCs of AV Del (see Fig. 8) needs only nine parameters, namely $D_1=D_2=D$, $\mathit{\Gamma}_1=\mathit{\Gamma}_2=\mathit{\Gamma}$, $C_1=C_2=C$, $a_{11},\,a_{12},\, a_{21},\,a_{22},\,a_{41},$ and $a_{42}$, $n_{\mathrm e}$=2, $n_{\mathrm p}=2, n_{\mathrm c}=0$, $A_3 \equiv 0$. See also Table 1.

**Figure 8.** The fit of the *BVR*$_{\mathrm{c}}$*I*$_{\mathrm{c}}$ LCs of a semidetached short periodic ‘cool Algol’ AV Del. Dark dots are observations, grey lines is the 13-parameter phenomenological fit. For details see Table 1 and Sect. 4.3.

<!-- figure:avdel file:fig8.eps -->

*[manual review: graphic not embedded; source file `fig8.eps`.]*

### 4.3. Brief description of selected eclipsing systems
<!-- section:select -->

TrES-3b is an extrasolar planet orbiting the star GSC  03089-00929 with a period of 31 hours. It belongs to the hot Jupiters which are undergoing orbital decay due to tidal effects. For the LC inspection (Fig. 3) $R$ photometry of 15 transits containing 2820 individual measurements in total (courtesy Vaňko et al. 2013) was used. The parameters of the LC fit of TrES-3b are in the legend of Fig. 3.

HD 209458 was the first star found to have a transiting planet (Charbonneau et al. 2000; Henry et al. 2000) and remains the second brightest star known to have a transiting planetary companion. Knutson et al. (2007) obtained 1066 spectra over four distinct transits with the STIS spectrometer on HST allowing to synthesize LCs in 10 spectrophotometric bandpasses in 290–1030 nm (see also Sect. 4.2, Fig. 6 and Mikulášek et al. 2015).

Table 1 contains the parameters of the phenomenological fit of LCs and some other information on the following selected eclipsing binaries:

- AR Aurigae, a prototype of a detached EB, (O'Connell 1979).
- EK Comae, an overcontact, spotted EB with a short orbital period, (Samec, Gray & Carrigan 1996).
- AV Delphinis, a ‘cool Algol’ consisting of a F type primary on the main sequence and a K subgiant filling its Roche lobe (Mader et al. 2005).
- V477 Lyrae, an unusual, detached EB consisting of a very hot and luminous nucleus of the planetary nebula as a primary component and a solar type star as secondary (Pollacco & Bell 1994).

Table 1 shows that the fit of LCs of the above mentioned stars by our ‘hi-fi’ models, quantified by the ratio $\rho$ is nearly the same or better than in the case of the fit of BM3 (CALEB) physical model (Bradstreet 2005).

## 5. Phenomenological model solution
<!-- section:solution -->

### 5.1. Finding of model parameters and their uncertainties
<!-- section:LSM -->

The procedure for finding model parameters is based on the simultaneous mathematical processing of all relevant photometric data consisting of individual photometric observations, including barycentric julian date of the $i$-th measurement $t_i$, the measured magnitude or magnitude difference corrected for possible trend(s) during nights or seasons $y_i$, and the estimate of its uncertainty $\sigma_i$. Furthermore, we should know the effective wavelengths of the photometric filter used, $\lambda_{\mathrm{eff}i} \mathrm{or} \mathit{\Lambda}_i$, and submission of an individual observation to one of the observational subsets $r_i$ (see Sect.3.1).

For simplicity we shall assume that the shapes of LCs are constant and the variability of an object is described by the unique model function Eq. (10), consisting of the instrumental term $Y_{r0}(t,\lambda_{\mathrm{eff}})$ (Eq. (11)) and the intrinsic phenomenological ES model LC function $F(\vartheta,\lambda_{\mathrm{eff}})$, specified in Sect. 4. The phase function $\vartheta(t,P_0, M_0, \dot{P}_0, \mathrm{or} \{\textit{O-C}\},\ldots)$ is a function of time and some free parameters of a variety of period models offered in Sect. 2. The result of the solution - the full set of $g$ free parameters of the complete model including the estimate of the parameter uncertainties was evaluated simultaneously using the non-linear least square method by minimising the quantity $\chi^2$ by the standard technique (using tried Newton-Raphson method of non-linear equation solution) well described in e.g. Press et al. (2002); Hayashi (2000); Hartkopf et al. (1989); Mikulášek et al. (2011b). With a good initial estimate of the parameter vectors the iterations converge fairly quickly.

**Figure 9.** The difference in mag between the physical model primary minimum of AR Aur and various alternatives of phenomenological basic function listed in Table 2.

<!-- figure:arsrov file:fig9.eps -->

*[manual review: graphic not embedded; source file `fig9.eps`.]*

All estimates of uncertainties of model parameters were computed using formulae taking into account that our models fit phase curves of EBs with uneven accuracy. Since the models are not orthogonal, uncertainties of the functions of model coefficients (typically the fits of LCs or minima times) should be computed by the general law of uncertainty propagation assuming also correlations among individual coefficients (see e.g. Bevington & Robinson 2003; Mikulášek & Zejda 2013). It is advisable to orthogonalize the models at least in the ephemeris parameters, in accordance with what we did in (Mikulášek 2007; Mikulášek et al. 2008).

### 5.2. The selection of an optimal model of light curves

**Table 2.** The list of alternatives for several phenomenological model functions of eclipses.

<!-- table:srov,table -->

|  | $F_{\mathrm{e}}(\varphi)$ | $s$ | parameters |
| --- | --- | --- | --- |
|  |  | mmag |  |
| 1 | $A\left[1\!+\!C\left(\frac{\varphi}{D}\right)^2\right]\left\{1\!-\!\left\{1\!-\! \exp\left[1\!-\!\cosh\left(\frac{\varphi}{D}\right)\right]\right\}^ {\mathit{\Gamma}}\right\}$ | 3.4 | $A,D,\mathit{\Gamma},C$ |
| 2 | $A\left\{1\!-\!\left\{1\!-\!\exp\left[1\!-\!\cosh\left(\frac{\varphi}{D}\right)\right] \right\}^{\mathit{\Gamma}}\right\}$ | 3.9 | $A,D,\mathit{\Gamma}$ |
| 3 | $A\left\{1\!-\!\left\{1\!-\!\exp\left[-\frac{1}{2}\left(\frac{\varphi}{D}\right)^2\right] \right\}^{\mathit{\Gamma}}\right\}$ | 5.5 | $A,D,\mathit{\Gamma}$ |
| 4 | $A \mathrm{Real}\left(1\!-\!\left\lvert\frac{\varphi}{D}\right\rvert^\mathit{\Gamma}\right)^{3/2}$ | 6.9 | $A,D,\mathit{\Gamma}$ |
| 5 | $A\exp\left[-\frac{1}{2}\left(\frac{\varphi}{D}\right)^2\right]$ | 11 | $A,D$ |
| 6 | $A\,\left(\frac{1}{2}\!-\!\left\lvert\frac{\varphi}{2\,D}\right\rvert+\left\lvert\left\lvert \frac{\varphi}{2\,D}\right\rvert\!-\!\frac{1}{2}\right\rvert\right)$ | 16 | $A,D$ |
| 7 | $A\exp\left[1\!-\!\cosh\left(\frac{\varphi}{D}\right)\right]$ | 18 | $A,D$ |

The fidelity of individual alternatives are illustrated by the Fig. 9 and quantified by the scatter $s$ of the fit of the ‘real’ light curve of primary minimum of AR Aur, simulated by its physical model. The model function number 4 was suggested by Andronov (2010, 2012), the function ‘Real’ extracts a real part of the argument.

The models of light curves should be tailored to the studied object/objects, available data, and the purpose of fitting the data. Especially, the number of used free parameters should be as few as possible, however without any serious influence on the accuracy and reliability of the results. It follows from our experience that it pays off to adhere to the following general principles:

1. It is always advantageous to process all available data simultaneously and not divided into parts. It is also valid for the determination of mid-eclipse times of individual eclipses where we should use the Eq. (9).
2. We have to pay attention to the right weighting of entered data as it is required by the used $\chi^2$ regression. If our original data do not content individual uncertainties, we have to estimate them iteratively from the scatter of residuals $\{\Delta y_i\}$ for appropriately created data subsets.
3. Fixing of LC model parameters, if they are known from previous analyses, is also advised. In addition, neglecting of all model terms whose amplitudes are less or comparable with their uncertainties, is recommended.
4. The number of free parameters can also be reduced by using simpler model functions of eclipses listed in Table 2. Suggested model functions are compared in Fig. 9.
5. The complexity of the selected phenomenological model should correspond to the purpose of the modelling. Several tasks (e.g. the basic classification of LCs) allow for the use of simple, unified models with basic parametric outfit.

Unfortunately, the effort of using the optimum ‘hi-fi’ phenomenological models considerably encumbers automation of the computational process. The diversity of real light curves of particular ESs requires that they be solved individually.

## 6. Period analysis of XY Bootis in 1955–2009
<!-- section:xyperchng -->

The above described phenomenological modelling of periodic variable stars has been developed first and foremost for the sake of the simultaneous period analysis of all available data containing phase information. Such data are in the case of ESs standardly times of light minima, LCs or their segments and radial velocity curves. The majority of studies of ES period changes were based on the analysis of *O-C* diagrams constructed using the times of light minima, where these timings were determined individually directly by observers not taking into account LCs of the star observed before. Several other studies were based only on the analysis of LCs obtained during several years. Measurements of radial velocities were used, namely, for the solution of the geometry of the system.

The simultaneous analysis of data of various kind is possible using an extended version of the contemporary sophisticated codes for the physical solution of eclipsing systems (see e.g. Hadrava 2004; Van Hamme & Wilson 2007; Wilson & Van Hamme 2014). The concept of EB period analyses without using *O-C* diagrams and the physical solution of the system was outlined (i.a.) in Mikulášek et al. (2011a, 2012a, 2013a), and studies of period changes of individual EBs (Zhu et al. 2010, 2012; Mikulášek et al. 2013b). The results of the preliminary report on the ephemeris of AR Aur – a star with the light time effect (Mikulášek et al. 2011b) – were referred to and extensively discussed by Wilson & Van Hamme (2014), who used AR Aur as an example of systems with a third companion.

Wilson & Van Hamme (2014) also studied the W UMa type eclipsing binary XY Bootis as a prototype of a close double star with a nearly steady period change. The study clearly proves the advantage of simultaneous processing of all relevant data. That is why we want to compare the results of this sophisticated study describing period change of XY Boo during the time interval 1955–2009 with our results based on strictly the same observational data.

### 6.1. XY Bootis

Eclipsing binary XY Bootis (= BD$+20^{\circ}2874$ = HIP 67431; $V_{\mathrm{max}}=10.3$ mag; Sp. F5V) was discovered as a variable star by Hoffmeister (1935). Tsesevich (1950, 1954) observed the star visually and classified it as an eclipsing binary of W UMa-type.

The first photoelectric observations were obtained by Hinderer (1960). Wood (1965) reanalysed Hinderer's data and found the true period of the star $P$ = $0.\!\!^{\mathrm{d}}37054$. Binnendijk (1971) observed six minima of XY Boo in $BV$, improved the ephemeris $(M_0=2440389.7321, P=0.\!\!^{\mathrm{d}}37055)$, and revealed remarkable increase in the period. Winkler (1977) observed XY Boo also in 1976 in $BV$ and derived three other times of minima (see Table 6). Awadalla & Yamasaki (1984) gave two new times of light minima and confirmed period increase. The history of the XY Boo investigation from its discovery to 1998 is described more extensively in Molík & Wolf (1998). McLean & Hilditch (1983) measured spectroscopically the radial velocity of both components and estimated the mass ratio $q=0.16\pm0.04$.

**Figure 10.** $BV$ curves of XY Boo (see the list in Table 5). The phase is plotted according to our quadratic ephemeris (see Table 4). The areas of points are proportional to their weights. Open squares are normal points (each of them represents the mean of about 50 measurements). Grey lines are fits by our phenomenological model (see Eq. (18) and Table 3). $\Delta B$ and $\Delta V$ display residuals of $BV$ magnitudes and normal points from the LC phenomenological model. The scale of residuals is two times larger than the measure of *BV* light curves.

<!-- figure:xyLCfig file:fig10.eps -->

*[manual review: graphic not embedded; source file `fig10.eps`.]*

The first detailed period study was done by Molík & Wolf (1998) who used 43 moments of minimum spanning the interval 1944–98 and calculated the quadratic ephemeris. The found record-breaking period increase $\dot{P}$ = 1.67(5)$\times 10^{-9}$= 5.3 s per century was explained by mass transfer of $1.34\times 10^{-7}$ M$_{\odot}$ yr$^{-1}$ from the secondary to the primary component. The results were confirmed and improved by Yang et al. (2005) who found $\dot{P}$ = 1.711(6)$\times 10^{-9}$= 5.4 s per century on the basis of standard *O-C* analysis of 54 minima times.

Wilson & Van Hamme (2014) combined in their calculations of the quadratic ephemeris of XY Boo phase information hidden in *BV* LCs obtained by Binnendijk (1971); Winkler (1977); Awadalla & Yamasaki (1984), $RV$ curves of McLean & Hilditch (1983), all times of minima listed in Yang et al. (2005) and other 33 minima timings collected in Table 1 of their article covering the interval 2005–09. Using all of those data they found the mean period increase $\dot{P}$ = 1.6348(8)$\times 10^{-9}$ = 5.159(24) s per century. They also noticed some oscillation from JD 2 448 000 to 2 455 000 with no indication of periodicity. We have now collected many other observations proving the complexity of the XY Boo period variations. Nevertheless, for the sake of the comparison of the effectiveness of our method, we used in the following small study exclusively those data used by Wilson & Van Hamme (2014).

### 6.2. Phenomenological model of XY Boo variability
<!-- section:xymod -->

We assumed, similarly as Wilson & Van Hamme (2014), that the instantaneous period $P(t)$ of XY Boo is lengthening with the constant rate $\dot{P}(t)=\mathrm{const.}$ Then the phase function $\vartheta(t)$ and the prediction of primary minimum times $\mathit{\Theta}(E)$ can be approximated (according to Eqs. (7), (8)) by simple relations:

$$
\vartheta=\vartheta_1-\dot{P}\,\frac{\vartheta_1^2}{2};\quad \mathit{\Theta}_{\mathrm{min}}=M_0+P_0\,E+{\frac{1}{2}}P_0\,\dot{P}\,E^2,
\tag{17}
$$
<!-- equation xytheta -->

where $\vartheta_1=(t-M_0)/P_0$, $M_0$ is the JD timing of the basic primary minimum - the origin of counting of epochs $E$, $P_0=P(t=M_0)$ is the instantaneous period at the time $t=M_0$. Integer doubling of epoch E is done (even for times of primary minima, odd for times of secondary minima)[^6].

Light curves of XY Boo with almost equally deep minima (see Fig. 10) agree with W UMa classification. We found that all of them can be well fitted by the following phenomenological model with nine free parameters: $a_{11},a_{12},a_{21},a_{22},A_3,A_4,D_1,D_2$, and $\mathit{\Gamma}$,

$$
\begin{aligned}
& F_{\mathrm{LC}}(\vartheta)=\sum_{k=1}^2 (a_{k1}+a_{k2}\mathit{\Lambda})\left\{1\!-\!\left\{1\!-\!\exp\left[1\!- \!\cosh\left(\frac{\varphi_k}{D_k}\right)\right] \right\}^{\mathit{\Gamma}}\right\}+ \\
&+\,A_3\cos(4\,\pi\,\vartheta)+A_4\cos(6\,\pi\,\vartheta); \\
& \varphi_k=\left[\vartheta-(k-1)/2\right] - \mathrm{round}\left[\vartheta-(k-1)/2\right],\quad \mathit{\Lambda}=\frac{550}{\lambda_{\mathrm{eff}}}-1.
\end{aligned}
\tag{18}
$$
<!-- equation xyLCeq -->

The results achieved using this phenomenological model of XY Boo $BV$ light curves are denoted as ‘Model I’.

Other LC templates were $BV$ synthetic LCs computed by the freely accessible W-D 2013 code with physical parameters of XY Boo published in Wilson & Van Hamme (2014). The results obtained using these $BV$ LC templates are denoted as ‘Model II’. Fig. 11 displays that the difference between the found phenomenological and synthetic $BV$ model LCs are only marginal; numerically it is also documented in Table 3.

**Table 3.** Nine parameters of phenomenological (this paper) and synthetic LCs (Wilson & Van Hamme 2014) models.

<!-- table:xycrv -->

| par. | Model I | W&VH | prm | solution I | W&VH |
| --- | --- | --- | --- | --- | --- |
| $a_{11}$ [mag] | 0.102(4) | 0.098 | $A_{4}$ [mag] | 0.0064(6) | 0.0075 |
| $a_{12}$ [mag] | 0.112(4) | 0.104 | $D_1$ | 0.0627(21) | 0.059 |
| $a_{21}$ [mag] | 0.050(10) | 0.056 | $D_2$ | 0.0558(20) | 0.053 |
| $a_{22}$ [mag] | 0.007(10) | 0.048 | $\mathit{\Gamma}$ | 0.97(6) | 0.95 |
| $A_{3}$ [mag] | 0.1081(19) | 0.111 |  |  |  |

For the meaning of parameters see Eq. (18).

**Figure 11.** Models of $B$ and $V$ LCs of XY Boo. Grey lines are *BV* model light curves simulated by the Wilson & Van Hamme (2014) physical model, dotted lines correspond to our phenomenological model (see Eq. (18) and Table 4); dashed lines are hypothetical *BV* LCs of XY Boo without mutual eclipses.

<!-- figure:xyLCmodfig file:fig11.eps -->

*[manual review: graphic not embedded; source file `fig11.eps`.]*

For the description of shapes of radial velocity $(RV)$ phase curves we used only a simple sinusoidal model (see Eq. (19)) neglecting the Rossiter-McLaughlin effect (McLaughlin 1924)

$$
RV_k(\vartheta)=V_{\gamma}+A_5 \left(k-1-q\right)\,\sin(2\,\pi\,\vartheta),
\tag{19}
$$
<!-- equation xyrveq -->

where $k=1$ refers to the first component, whilst $k=2$ to the secondary one, $V_{\gamma}$ is so-called $\gamma$ velocity, $A_5$ is the amplitude of the difference in the radial velocity between the components, all in km s$^{-1}$, and $q=m_2/m_1$ is the ratio of component masses.

This approximation is fully sufficient for $RV$ observations of McLean & Hilditch (1983) that cover only about 15 % of the phase curve. Results are in the bottom part of Table 4.

**Table 4.** Comparison of common parameters derived by Wilson & Van Hamme (2014) and us.

<!-- table:xypar -->

| par. | W & VH | Model I | Model II |
| --- | --- | --- | --- |
| all |  |  |  |
| $\dot{P}$ | $1.6348(77) \times 10^{-9}$ | $1.6328(52)\times 10^{-9}$ | $1.6442(47)\times 10^{-9}$ |
| $P_0$ | $0.\!\!^{\mathrm{d}}370\,560\,205(18)$ | $0.\!\!^{\mathrm{d}}370\,560\,213(14)$ | $0.\!\!^{\mathrm{d}}370\,560\,198(12)$ |
| $M_0^*$ | 0.35163(28) | 0.35185(26) | 0.35143(27) |
| LC |  |  |  |
| $\dot{P}$ | $1.497(37) \times 10^{-9}$ | $1.506(24)\times 10^{-9}$ | $1.502(25)\times 10^{-9}$ |
| $P_0$ | $0.\!\!^{\mathrm{d}}370\,559\,889(92)$ | $0.\!\!^{\mathrm{d}}370\,559\,913(70)$ | $0.\!\!^{\mathrm{d}}370\,559\,898(71)$ |
| $M_0^*$ | 0.35162(29) | 0.35174(30) | 0.35164(30) |
| $T_{\mathrm m}$ | W & VH | this paper |  |
| $\dot{P}$ | $1.729(27) \times 10^{-9}$ | $1.745(26)\times 10^{-9}$ |  |
| $P_0$ | $0.\!\!^{\mathrm{d}}370\,559\,58(11)$ | $0.\!\!^{\mathrm{d}}370\,559\,86(10)$ |  |
| $M_0^*$ | 0.3565(21) | 0.3490(11) |  |
| $RV$ | W & VH | this paper |  |
| $V_{\gamma}$ | $7.7\pm6.6$ | $8\pm7$ |  |
| $q$ | $0.159\pm0.048$ | $0.154\pm0.037$ |  |
| $A_5$ | $286\pm24$ | $282\pm23$ |  |

$M_0^*= \mathrm{HJD}-2\,444\,716$, $V_{\gamma}$ and $A_5$ are expressed in km s$^{-1}$.

*[manual review: some source rows have fewer cells than the widest row. Empty cells were added. Short rows begin with: all; LC; $T_{\mathrm m}$; $\dot{P}$; $P_0$; $M_0^*$; $RV$; $V_{\gamma}$; $q$; $A_5$.]*

### 6.3. Used data and their weights. Models I and II

Our period analyses of XY Boo was based on 1770 individual data points (see the list in Table 5) acquired by three different techniques divided into 9 groups with various scatters $\sigma_{\mathrm {I}}$ and $\sigma_{\mathrm {II}}$ with respect to phenomenological (I), and synthetic (II), model phase curves.

Scatter $\sigma_{\mathrm {I}}$ used to be the same or a bit smaller than the scatter $\sigma_{\mathrm {II}}$ with respect to computed synthetic phase curves (Wilson & Van Hamme 2014). Scatters of radial velocity measurements – $\sigma_{RV \mathrm{I}}$ and $\sigma_{RV \mathrm{II}}$ 28 and 30 km s$^{-1}$ – seems to be a good estimate of their values. The mean uncertainty of eclipse times[^7] $\sigma_{\mathrm{Tmin}}$ with respect to the model Eq. (17) is $0.\!\!^{\mathrm{d}}0043=6.2$ min. It should be mentioned that the inner uncertainty of individual times of minima is typically one order better. The uncertainty $\sigma_{\mathrm{Tmin}}$ is caused mainly by erratic fluctuations in the rate of the orbital period and the shape of LCs. The character of these changes is well displayed in Fig. 12.

**Figure 12.** XY Boo timing residuals from the quadratic ephemeris (with a $\dot{P}$ term). Published minima timings are denoted as squares, timings derived from LCs are circles which areas are proportional to their weight.

<!-- figure:xyOCkva file:fig12.eps -->

*[manual review: graphic not embedded; source file `fig12.eps`.]*

Scatter $\sigma_{\mathrm {I, II}}$ for an individual subset of data (see Table 5) served as the basis for weighting of each used measurement and interconnection of data of various nature. It enabled applying of $\chi^2$ regression computation outlined in Sect. 5. The computation represents the solution of 21 (case I) or 12 (case II) non-linear equations of 21 or 12 free parameters. The difference in the number of parameters needed is a result of the fact that in case II we adopted template LCs from paper Wilson & Van Hamme (2014). This means that we fixed all 9 parameters that we needed for the determination of $BV$ template LCs.

**Table 5.** The list of used observational data including their source, number, specification, and scatter with respect to phenomenological model phase curves (Model I) and synthetic phase curve (Model II).

<!-- table:xyobs -->

| source | type | N | spec | $\quad \sigma_{\mathrm I}$ | $\quad \sigma_{\mathrm {II}}$ |
| --- | --- | --- | --- | --- | --- |
| Binnendijk (1971) | light | 440 | $B$ | 0.011 mag | 0.011 mag |
|  | curves | 441 | $V$ | 0.0084 mag | 0.0087 mag |
| Winkler (1977) | light | 99 | $B$ | 0.021 mag | 0.020 mag |
|  | curves | 109 | $V$ | 0.022 mag | 0.023 mag |
| Awadala (1984) | light | 280 | $B$ | 0.021 mag | 0.023 mag |
|  | curves | 284 | $V$ | 0.025 mag | 0.026 mag |
| McLean (1983) | radial | 12 | I | 28 km s$^{-1}$ | 28 km s$^{-1}$ |
|  | vel. | 10 | II | 30 km s$^{-1}$ | 30 km s$^{-1}$ |
| Yang et al. (2005) | eclipse | 75 | I+II | 0.0043 d | 0.0043 d |
| +W&V(2014) | timings |  |  |  |  |

*[manual review: some source rows have fewer cells than the widest row. Empty cells were added. Short rows begin with: +W&V(2014).]*

In the first part of solutions I and II we obtained the parameters of the unified XY Boo ephemerides: $M_0$, $P_0$, and $\dot{P}$ (see Table 4), which can be compared with the same parameters listed in Table 3 of Wilson & Van Hamme (2014) paper. Computed parameters of the $B$, $V$, and $RV$ phase curves according to these ephemerides are in Table 3 and Table 4, respectively. In the second part of the solutions we derived 12 virtual eclipse times and their uncertainties by means of the model Eq. (9) from $BV$ photometry and $RV$ data - see Table 6, Fig. 12, 13.

**Figure 13.** XY Boo timing residuals from the linear ephemeris (without a $\dot{P}$ term). Published minima timings are denoted as squares, timings derived from LCs are circles which areas are proportional to their weight, and a timing derived from radial velocity curves is noted as a diamond.

<!-- figure:xyOClin file:fig13.eps -->

*[manual review: graphic not embedded; source file `fig13.eps`.]*

### 6.4. Discussion of results. Comparison with W&VH solution
<!-- section:xyresults -->

#### 6.4.1. General remarks

We discuss here the results of three methods for period analysis that enables the processing of various type of data containing phase information. For their consistent comparison we used exactly the same observational data set specified in the paper of Wilson & Van Hamme (2014) and the assumption that the period $P$ rises uniformly with time: $P(t)=P_0+\dot{P}\,(t-M_0)$, where $\dot{P}=\mathrm{const}$.

Model I uses the phenomenological model for the $BV$ LCs (Eq. (18)), whilst hybrid Model II uses synthetic LCs computed by Wilson & Van Hamme (2014). This technique is the one used e.g. by Zasche et al. (2014); Zasche (2015). Both models assume strictly circular orbits of components and synchronous rotation. They also suppose that the shape of LCs given, namely, by the variable geometry of the orbiting system, are more or less constant.

On the contrary, detailed inspection of the LCs proves that there are apparent changes on various time scales (see Fig. 14 and $BV$ light curves in Fig. 3 in Wilson & Van Hamme 2014). Some of them can be attributed to instrumental effects like red noise (Pont et al. 2006) or incomplete detrending of LCs. Others are due to intrinsic changes of the object itself, such a chromospheric and spot activity or shifts due to unsteady mass transfer between components (see the right part of Fig. 12).

**Table 6.** Comparison of the eclipse timings of XY Boo.

<!-- table:xytmin -->

| publ. timing | Model I | Model II | (*O-C*)$_{\mathrm{I}}$[d] | epoch | aut |
| --- | --- | --- | --- | --- | --- |
| 39 950.8121 | .81207(16) | .81207(16) | -0.00024 | -12860.5 | B |
| 39 951.9243 | .92427(14) | .92430(13) | 0.00030 | -12857.5 | B |
| 39 953.7763 | .77635(13) | .77628(13) | -0.00038 | -12852.5 | B |
| 39 953.9626 | .96259(20) | .96261(21) | 0.00058 | -12852.0 | B |
| 40 298.9470 | .94746(16) | .94745(16) | 0.00089 | -11921.0 | B |
| 40 389.7319 | .73142(13) | .73145(13) | -0.00065 | -11676.0 | B |
| 42 569.7091 | .70875(55) | .70875(55) | 0.00212 | -5793.0 | W |
| 42 577.6745 | .67530(65) | .67535(65) | 0.00173 | -5771.5 | W |
| 42 582.6769 | .6750(12) | .6750(12) | -0.00108 | -5758.0 | W |
| 45 131.3793 | .3800(11) | .3800(10) | 0.00047 | 1120.0 | A |
| 45 132.3056 | .30470(80) | .30450(85) | -0.00126 | 1122.5 | A |
| 44 325. | .446(16) | .446(16) | 0.03500 | -1055.0 | RV |

Published timings of Binnendijk (1971), Winkler (1977), and Awadalla & Yamasaki (1984) are compared with our results (only the fraction is given) and their uncertainties derived from LCs and RV curves. (*O-C*)$_{\mathrm{I}}$ is the residual of the found eclipse timing to quadratic ephemeris according to the Model II, $N$ is the number of photoelectric observations used for the timing determination.

#### 6.4.2. Unified ephemerides. Virtual eclipse times
<!-- section:xyuniefem -->

All quantitative results achieved by the three discussed models which can be directly compared are listed in Table 4. It is apparent that especially the increase of the orbital period $\dot{P}$, the period $P_0=P(t=M_0)$, and the time of the basic primary minimum $M_0$ derived from all data, from LCs only and from eclipse times, are identical within their uncertainties. The results derived from the analysis of radial velocity measurements are in very good concordance as well. We are convinced that this conclusion is valid not only for XY Boo  but also for other eclipsing systems.

There is an apparent identical discrepancy found by this paper and Wilson & Van Hamme (2014) in the value of the mean deceleration $\dot{P}$ derived only from LC shifts and/or eclipse times ($T_{\mathrm m}$) (see Table 4, rows LC and $T_{\mathrm m}$): $\dot{P}_{\mathrm {LC}}=1.506(24)\times10^{-9}$, $\dot{P}_{T_{\mathrm m}}=1.745(26)\times10^{-9}.$

The first possible explanation, that it is the result of different distribution of LCs and times data along the *O-C* diagram (see Fig. 13, 12) and the inconstancy of $\dot{P}$ where $\ddot{P}>0$), has proven to be false. We tested the period models with $\ddot{P}$ term and found that $\ddot{P}=0(4) \times 10^{-15}$ d$^{-1}$. The effect is then very likely caused by the presence of the pair of eclipse minima of Hinderer (1960) at the very beginning of the *O-C* diagram (see Fig. 12) that significantly deviates from its parabolic prediction. However, our thorough inspection of the original Hinderer's measurements showed that both eclipse times are correct.

Models I and II enabled calculation of ‘virtual eclipse times’ for selected subsets of photometric and radial velocity data using the relation Eq. (9). These times, including their uncertainties, are listed in Table 6 together with eclipse times[^8] published by authors of $BV$ photometries – Binnendijk (1971); Winkler (1977); Awadalla & Yamasaki (1984) The results as well as their uncertainties obtained by Model I and Model II are nearly identical. The last ones are very important as they enable the evaluation of real inner accuracy of individual times, the construction of precise *O-C* diagrams (Mikulášek et al. 2011a), and the discussion of subtle problems of stability of the period, variability of LCs etc. There is no systematic difference between the published eclipse timings (see the first column of Table 6) and those derived by our Models.

The excellent agreement of comparable results obtained by all three models proves that they can be used as good alternatives in solving common tasks of the eclipse system period analysis.

**Figure 14.** Residua of $BV$ light curves of Binnendijk (1971); Winkler (1977); Awadalla & Yamasaki (1984) clearly show variations in LC shapes. $B$ and $V$ residuals are denoted as circles and open squares, respectively.

<!-- figure:xyLCresfig file:fig14.eps -->

*[manual review: graphic not embedded; source file `fig14.eps`.]*

#### 6.4.3. *BV* and *RV* phase curves
<!-- section:xyphasecrv -->

The differences between the phenomenological and the synthetic $BV$ light curves are insignificant – they represent about 0.5% of the amplitude of the light changes (see Fig. 11). The parameters of the phenomenological model of both mentioned LCs are in Table 3. It seems that phenomenological modelling is a good method for expressing common types of LCs using only a very small number of parameters.

The fit of the observed $BV$ light curves by Model I is fairly good (see Fig. 10) – scatter of normal points in $B$ and $V$ are better than 0.004 and 0.003 mag. The larger part of this scatter is caused by the erratic variability of LCs due to stellar activity and inconstant O'Connell effect. The changes of LC shapes are clearly visible in the phase diagram of $BV$ residuals (Fig. 14) for all three photometric data sets.

The detailed inspection of measurements of Binnendijk (1971) shows weak and variable O'Connell effect (data from 1968 and 1969 displayed O'Connell effect of the opposite sign), whilst residuals of Winkler (1977) and Awadalla & Yamasaki (1984) are dominated by double wave going in antiphase. It seems that such seasonal variations in light curve shapes are quite common. Sometimes they can be much more dramatic (see e.g. changes in LCs of notorious XY UMa, Lister et al. 2001). These LC changes lowered the accuracy of the fit and eclipse timing determination.

Yet unpublished observations of XY Boo obtained during one month (Mikulášek et al. 2016) prove that the time scale of LC changes is usually shorter than several days.

## 7. Conclusions
<!-- section:conclusions -->

Phenomenological modelling presents an admissible alternative for the solution of selected ES research tasks. We state that:

1. The estimation of parameters and their uncertainties obtained by our phenomenological (and also hybrid) modelling and other well-proven methods, including solutions by sophisticated physical models of eclipsing systems, are almost the same (see e.g. Sect. 4.3 and 6.4).
2. Phenomenological modelling is based on the minimization of the $\chi^2$ sum, which enables the simultaneous processing of different sources of phase information (complete LCs and their segments, radial velocity curves, individual mid-eclipse times etc.).
3. Simple model function of eclipses (Eq. (13)) can be also used for good determination of mid-eclipse times and their uncertainties of individual observations of stellar eclipses (our model has been standardly used for the determination of time minima of original observations of EBs by Variable star and Exoplanet Section of Czech Astronomical Society since 2011, Brát et al. 2012)
4. As a by-product of the phenomenological modelling we obtain the list of virtual minima times derived from LC data which help us i.a. to quickly check the selected phenomenological model of LCs or period variability (see Sect. 6.4.2).
5. Light curve model parameters can be used for the apt description of both one-colour and multicolour LCs of eclipsing systems. For example, shapes of ten curves of HST spectrophotometry (320–980 nm) of the exoplanet transit of HD 209 458b, taken from Knutson et al. (2007), are determined by only nine parameters (see Mikulášek et al. 2015). We can use this application e.g. for description and classification of observed LCs of eclipsing systems.
6. Knowing the template of LCs (from physical models or observed LC of superior quality) we can quickly modify the presented phenomenological model and establish a hybrid model (Model II in Sect. 6) with the diminished number of free parameters. As we showed in Sect. 6, the results of this approach are the same results as physical or pure phenomenological modelling. However, application of the latter method is much faster.
7. Phenomenological (and also hybrid) modelling of an ES could solve standard tasks of ES research (based on every sources of phase information), especially the improvement of ES ephemeris for standard period models of:

   - systems with constant period,
   - systems in a steady regime of mass and angular momentum transfer between components (e.g. XY Boo, Sect. 6),
   - systems with erratic changes of period – phase function is here approximated using so-called *O-C* time shifts of the observed phase curves versus the predicted LC derived by the period model with fixed parameters (typically $P_0,M_0$ or $P_0,M_0,\dot{P}$) - see Eq. (9), and Sect. 6.4.2,
   - eclipsing systems influenced by the gravitational attraction of a third body (see the preliminary paper about AR Aur in Mikulášek et al. 2011b, and the discussion in Wilson & VanHamme 2014)[^9].

Phenomenological modelling of eclipsing systems presented above has also its disadvantages and limitations:

- The method does not provide direct information about the geometry and physics of eclipsing systems, especially the inclination of the system, relative radii, temperatures and the form of components.
- The phenomenological models of EBs light curves in their proposed form are not able to achieve an accuracy better than 0.5 % of their total amplitude of them (the accuracy of Kepler or CoRoT light curves is better by one or more orders). Nevertheless, such uncertainty is fully acceptable for many application.
- It may be a bit troublesome for beginners to select the optimum model of LCs. Using an inappropriate model may lead to nonconvergent or bad solutions.
- Phenomenological modelling of ESs has not been made available in such a user-friendly format as other modern physical models (e. g. Hadrava 2004; Prša et al. 2008, 2011; Wilson & Devinney 1971) until now.

Phenomenological modelling, influenced by modern physical models, has been developed gradually since 2008 (Mikulášek et al. 2008), its elements and principles were used in the majority of papers of this paper's author. The detailed applications of the presented bases of the method will be published elsewhere.

## Acknowledgements

The author is very indebted to many of his collaborators, namely to M. Zejda, S. de Villiers, M. Chrastina, M. Jagelka, J. Krtička, J. Liška, E. Paunzen, T. Pribulla, S.-B. Qian, M. Vaňko, R. E. Wilson, L.-Y. Zhu, and others, for their help with this arduous theme. The work on the paper was partly sponsored by the grants Ministry of education of Czech Republic II LH14300 and GA ČR 13-10589S.

## References

- Andronov, I. L. 2010, in Int. Conf. KOLOS-2010 Abstr. Booklet, Snina 2010, Slovakia, 1
<!-- key:and10; citation: Andronov (2010) -->

- Andronov, I. L., 2012, Astrophysics, 55, 536
<!-- key:and12; citation: Andronov (2012) -->

- Awadalla, N. S. & Yamasaki, A. 1984, Ap&SS, 107, 347
<!-- key:awa; citation: Awadalla & Yamasaki (1984) -->

- Beaky, M. M. & Koju, V. 2012, American Astronomical Society, 220, 333.03
<!-- key:beaky; citation: Beaky & Koju (2012) -->

- Bevington, P. R., & Robinson, D. K., in Data Reduction and Error Analysis for the Physical Sciences (3rd ed.), ISBN-10: 0072472278 , McGraw-Hill, 2003
<!-- key:bevington; citation: Bevington & Robinson (2003) -->

- Binnendijk, L. 1971, AJ, 76, 923
<!-- key:bin; citation: Binnendijk (1971) -->

- Bradstreet, D. H. 2005, The Society for Astronomical Sciences 24th Annual Symposium on Telescope Science, 2005. Published by SAS, 23
<!-- key:BM3; citation: Bradstreet (2005) -->

- Brát, L., Mikulášek, Z., & Pejcha, O. 2012, http://var2.astro.cz/library/ 1350745528_ebfit.pdf
<!-- key:brat; citation: Brát et al. (2012) -->

- Charbonneau, D., Brown, T. M., Latham, D. W., & Mayor, M. 2000, ApJ, 529, L45
<!-- key:charb; citation: Charbonneau et al. (2000) -->

- Chrastina, M., Mikulášek, Z., & Zejda, M. 2013, in Setting a New Standard in the Analysis of Binary Stars, ed. K. Pavlovski, A. Tkachenko & G. Torres, EAS Publications Series, 64, 383
<!-- key:chra; citation: Chrastina et al. (2013) -->

- Claret, A. & Gimenénez, V. 1993, A&A, 277, 487
<!-- key:claret; citation: Claret & Gimenénez (1993) -->

- Conroy, K. E., Prša, A., Stassun, K. G., Orosz, J. A., Fabrycky, D. C., et al. 2014, AJ, 147, 45
<!-- key:conroy; citation: Conroy et al. (2014) -->

- Davidge, T. J. & Milone, E. F. 1984, ApJS, 55, 571
<!-- key:davmil; citation: Davidge & Milone (1984) -->

- Drechsel, H., Rahe, J., Wargau, W., & Wolf, B. 1982, A&A, 110, 246
<!-- key:svicen; citation: Drechsel et al. (1982) -->

- Goldman, I., & Mazeh, T. 1991, ApJ, 376, 260
<!-- key:goldma; citation: Goldman & Mazeh (1991) -->

- Hadrava, P. 2004, Publ. Astron. Inst. Czechosl. Acad. Sci., 92, 1
<!-- key:had; citation: Hadrava (2004) -->

- Hartkopf, W. I., McAlister. H. A., & Franz, O. G. 1989, AJ, 98, 1014
<!-- key:hart; citation: Hartkopf et al. (1989) -->

- Hayashi, F. 2000, Econometrics, Princeton Univ. Press, ISBN 0-691-01018-8
<!-- key:hayashi; citation: Hayashi (2000) -->

- Henry, G. W., Marcy, G. W., Butler, R. P., & Vogt, S. S. 2000, ApJ, 529, L41
<!-- key:henry; citation: Henry et al. (2000) -->

- Hilditch, R. W. 2001, An Introduction to Close Binary Stars, Cambridge University Press, UK, ISBN 0-521-79800-0
<!-- key:hilda; citation: Hilditch (2001) -->

- Hinderer, F. 1960, Obs., 43, 161
<!-- key:hind; citation: Hinderer (1960) -->

- Hoffmeister, C. 1935, Astron. Nachr., 255, 401
<!-- key:hoff; citation: Hoffmeister (1935) -->

- Kallrath, J. & Milone, E. F. 1998, Eclipsing Binary Stars, Modelling and Analysis, ISBN 0-387-98622-7 Springer-Verlag New York Berlin Heidelberg
<!-- key:kalmil; citation: Kallrath & Milone (1998) -->

- Kalimeris, A., Rovithis-Livaniou, H., & Rovithis, P. 1997, A&A, 35, 69
<!-- key:kalimero; citation: Kalimeris et al. (1994) -->

- Kaluzny, J. & Rucinski, S. M. 1986, AJ, 92, 666
<!-- key:kal; citation: Kaluzny & Rucinski (1986) -->

- Kholopov, P. N. 1981, Premennyje zvezdy, 21, 465
<!-- key:chol; citation: Kholopov (1981) -->

- Kopal, Z. 1978, Dynamics of Close Binary Systems, Reidel, Dordrecht, Holland
<!-- key:kopal; citation: Kopal (1978) -->

- Knutson, H. A., Charbonneau, D., Noyes, R. W. et al. 2007, ApJ, 655, 564
<!-- key:knut; citation: Knutson et al. (2007) -->

- Kwee, K. K., van Woerden, H. 1956, Bull. Astron. Inst. Neth., 9, 252
<!-- key:kwee; citation: Kwee & van Woerden (1956) -->

- Lacy, C. H. S., Torres, G., Claret, A., & Sabby, J. A. 2003, AJ, 126, 1905
<!-- key:lacy; citation: Lacy et al. (2003) -->

- Lister, T. A., Collier C., A., Hilditch, R. W. 2001, MNRAS, 326, 1489
<!-- key:lister; citation: Lister et al. (2001) -->

- Liška, J., Skarka, M., Mikulášek, Z., Zejda, M., Chrastina, M. 2015, A&A, submitted, 2015arXiv15020333
<!-- key:liska; citation: Liška et al. (2015) -->

- Mader, J. A., Torres, G., Marschall, L. A., & Rizvi, A. 2005, AJ, 130, 234
<!-- key:mader; citation: Mader et al. (2005) -->

- Mandel, K. & Agol, E. 2002, ApJ, 580, 171
<!-- key:mandel; citation: Mandel & Agol (2002) -->

- McLaughlin D. B. 1924, ApJ, 60, 22
<!-- key:laugh; citation: McLaughlin (1924) -->

- McLean, B. J. & Hilditch, R. W. 1983, MNRAS, 203, 1
<!-- key:lean; citation: McLean & Hilditch (1983) -->

- Mikulášek, Z. 2007, Odessa Astron. Publications, 20, 138
<!-- key:mikort; citation: Mikulášek (2007) -->

- Mikulášek, Z. et al. 2016, in preparation
<!-- key:mikxy; citation: Mikulášek et al. (2016) -->

- Mikulášek, Z. & Gráf, T. 2005, Contr. Astron. Obs. Skalnaté Pleso, 35, 83
<!-- key:mikgr; citation: Mikulášek & Gráf (2005) -->

- Mikulášek, Z., Gráf, T., Zejda, M. et al. 2012b, ArXiv1212.5527
<!-- key:mikgra; citation: Mikulášek et al. (2012b) -->

- Mikulášek, Z., Chrastina, M., Liška J. et al. 2014, Contr. Astron. Obs. Skalnaté Pleso, 43, 382
<!-- key:mikKW; citation: Mikulášek et al. (2014) -->

- Mikulášek, Z., Krtička, J., Henry, G. W. et al. 2008, A&A, 485, 585
<!-- key:mik901; citation: Mikulášek et al. (2008) -->

- Mikulášek, Z., Krtička, J., Henry, G. W. et al. 2011b, A&A, 534, L5
<!-- key:mikcu; citation: Mikulášek et al. (2011b) -->

- Mikulášek, Z., Zejda, M., Chrastina, M., Qian, S.-B., & Zhu, L.-Y. 2013, in Setting a New Standard in the Analysis of Binary Stars, ed. K. Pavlovski, A. Tkachenko & G. Torres, EAS Publications Series, 64, 299
<!-- key:mikeas; citation: Mikulášek et al. (2013a) -->

- Mikulášek, Z., Wolf, M.,Zejda, M., & Pecharová, P. 2007, Ap&SS, 304, 363
<!-- key:mikext; citation: Mikulášek et al. (2006) -->

- Mikulášek, Z. & Zejda, M., in Úvod do studia proměnných hvězd, ISBN 978-80-210-6241-2, Masaryk University, Brno 2013
<!-- key:mikzej; citation: Mikulášek & Zejda (2013) -->

- Mikulášek, Z., Zejda, M., & Janík, J. 2012a, in IAU Symp. 282, From Interacting Binaries to Exoplanets: Essetial Modelling Tools, ed. M. T. Richards & I. Hubený (Cambridge: Cambridge Univ. Press), 391
<!-- key:miktatry; citation: Mikulášek et al. (2012a) -->

- Mikulášek, Z., Zejda, M., Pribulla, T. et al. 2015, in Astronomical Society of the Pacific Conference Series - Litomyšl 2014, in press, arXiv1502.07477
<!-- key:mikcon; citation: Mikulášek et al. (2015) -->

- Mikulášek, Z., Zejda, M., Qian, S.-B., & Zhu, L.-Y. 2011, in 9th Pacific Rim Conference on Stellar Astrophysics. ASP Conference Series, 451, ed. S. Qian, K. Leung, L. Zhu, & S. Kwok. San Francisco: ASPS, 111
<!-- key:miklijiang; citation: Mikulášek et al. (2011a) -->

- Mikulášek, Z., Zejda, M., Zhu, L. Y. et al. 2013, Central European Astrophysical Bulletin, 37, 145
<!-- key:mikbs; citation: Mikulášek et al. (2013b) -->

- Mikulášek, Z., Zverko, J., Krtička, J. et al. 2007, in Physics of Magnetic Stars, Proceedings of the conference Nizhnyi Arkhyz 28-31 Aug. 2006, eds. I. Romanyuk & D. Kudryavtsev, 300
<!-- key:mikzoo; citation: Mikulášek et al. (2007) -->

- Mikulášek, Z., Žižňovský, J., Zejda M., et al. 2011, in Magnetic Stars. Proceedings of the International Conference, ed. I. I. Romanyuk & D. O. Kudryavtsev (Nizhny Arkhyz: SAO), 431
<!-- key:mikar; citation: Mikulášek et al. (2011b) -->

- Molík, P. & Wolf, M. 1998, IBVS, 4640
<!-- key:mol; citation: Molík & Wolf (1998) -->

- O'Connell, D. J. K. 1979, Ric. Astron. Specola Vaticana, 8, 563
<!-- key:con; citation: O'Connell (1979) -->

- Nedoroščík, J., Vaňko, M., & Parimucha, Š. 2012, in IAU Symp. 282, From Interacting Binaries to Exoplanets: Essetial Modelling Tools, ed. M. T. Richards & I. Hubený (Cambridge: Cambridge Univ. Press), 73
<!-- key:nedor; citation: Nedoroščík et al. (2012) -->

- Nordstrom, B. & Johansen, K. T. 1994, A&A, 282, 787
<!-- key:nord; citation: Nordström & Johansen (1994) -->

- North, P. 1984, A&AS, 55, 259
<!-- key:north; citation: North (1984) -->

- Pollaco, D. L. & Bell, S.A., 1994, MNRAS, 267, 452
<!-- key:pol; citation: Pollacco & Bell (1994) -->

- Pont, F., Yucker, S., & Queloz, D. 2006, MNRAS, 373, 23
<!-- key:pont; citation: Pont et al. (2006) -->

- Press, W. H., Teukolsky, S. A., Vetterling, W. T. & Flannery, B. P. 2002, Numerical recipes in C++ : the art of scientific computing, by William H. Press, ISBN: 0521750334
<!-- key:press; citation: Press et al. (2002) -->

- Pribulla, T. 2012, in IAU Symp. 282, From Interacting Binaries to Exoplanets: Essetial Modelling Tools, ed. M. T. Richards & I. Hubený (Cambridge: Cambridge Univ. Press), 279
<!-- key:prib12; citation: Pribulla (2012) -->

- Pribulla, T., Vaňko, M., Ammler-von Eiff M. et al. 2012, Astron. Nachr., 333, 754
<!-- key:pribulla; citation: Pribulla et al. (2012) -->

- Prša, A., & Zwitter, T. 2005, ApJ, 628, 426
<!-- key:prsa05; citation: Prša & Zwitter (2005) -->

- Prša, A., Guinan, E. F., Devinney, E. J. et al. 2008, ApJ, 687, 542
<!-- key:prsa08; citation: Prša et al. (2008) -->

- Prša, A., Matijević, G., Latković, O., Vilardell, F., & Wils, P. 2011, Astrophysics Source Code Library, 6002
<!-- key:prsa11; citation: Prša et al. (2011) -->

- Qian, S.-B., He, J., Xiang, F., Ding, X., & Boonrucksar, S. 2005, AJ, 129.1686
<!-- key:qian3; citation: Qian et al. (2005) -->

- Rucinski, S. M. 1973, Acta Astron., 23, 79
<!-- key:ruc; citation: Rucinski (1973) -->

- Russell, H. N. & Merill, J. E. 1952, Princeton. Obs. Contr. 26, 1
<!-- key:rusmer; citation: Russell & Merrill (1952) -->

- Samec, R. G., Gray, J. D., & Carrigan, B.J., 1996, Observatory, 116, 75
<!-- key:samec; citation: Samec, Gray & Carrigan (1996) -->

- Selam, S. O. 2004, A&A, 416, 1097
<!-- key:selam; citation: Selam (2004) -->

- Tsesevich, V. P. 1950, Astron. Circ. Kazan, 100, 18
<!-- key:ces50; citation: Tsesevich (1950) -->

- Tsesevich, V. P. 1954, Odessa Izv., 4, 137
<!-- key:ces54; citation: Tsesevich (1954) -->

- Tsesevich, V. P. 1971, Eclipsing Binary Stars (in Russian), Nauka, Moscow
<!-- key:ces71; citation: Tsesevich (1971) -->

- Van Hamme, W. V. & Wilson, R. E. 2007, ApJ, 661, 1129
<!-- key:van; citation: Van Hamme & Wilson (2007) -->

- Vaňko, M., Maciejewski, G., Jakubík, M. et al. 2013, MNRAS, 432, 944
<!-- key:vanko; citation: Vaňko et al. (2013) -->

- Wilsey, N. J & Beaky, M. M. 2009, Society for Astronomical Sciences Annual Symposium, 28, 107
<!-- key:wilsey; citation: Wilsey & Beaky (2009) -->

- Wilson, R. E., & Devinney, E. J. 1971, ApJ, 166, 605
<!-- key:wilson; citation: Wilson & Devinney (1971) -->

- Wilson, R. E., & Van Hamme, W. 2014, ApJ, 780, 151
<!-- key:wilson14; citation: Wilson & Van Hamme (2014) -->

- Winkler, L. 1977, AJ, 82, 648
<!-- key:winkler; citation: Winkler (1977) -->

- Wood, R. 1965, Observatory, 85, 258
<!-- key:wood; citation: Wood (1965) -->

- Yang, Y. G., Qian, S. B., & Zhu L. Y. 2005, AJ, 130, 2252
<!-- key:yang; citation: Yang et al. (2005) -->

- Zahn, J.-P. 1992, in Binaries as Tracers of Stellar Formation, eds. A. Duquennoy, M. Mayor, Cambridge University Press, 253
<!-- key:zahn; citation: Zahn (1992) -->

- Zasche, P. 2015, New Astronomy, 34, 253
<!-- key:zasche15; citation: Zasche (2015) -->

- Zasche, P., & Wolf, M. 2013, A&A, 558, A51
<!-- key:zasche13; citation: Zasche & Wolf (2013) -->

- Zasche, P., Wolf, M., Vraštil, J. et al. 2014, A&A, 572, A71
<!-- key:zasche14; citation: Zasche et al. (2014) -->

- Zhu, L., Qian, S.-B., Mikulášek, Z. et al. 2010, AJ, 140, 215
<!-- key:zhudd; citation: Zhu et al. (2010) -->

- Zhu, L., Zejda, M., Mikulášek, Z. et al. 2012, AJ, 144, 37
<!-- key:zhubs; citation: Zhu et al. (2012) -->

<!-- Footnotes from the source, in order of appearance. -->

[^1]: The presented models may also be applied for expressing light intensity variations, but the treatment of data in the magnitude domain is more straightforward and the accuracies of results are almost the same.

[^2]: Observed orbital period may change due to possible transfer of matter between components or light time effect.

[^3]: Applying so-called *phase rectification* (Mikulášek et al. in preparation) we are also able to solve eccentric systems. The technique symmetrizes light curves of eclipsing binaries with components moving unevenly on their eccentric orbits by the rectification of their phase functions. The method of phase rectification enables also the effective analysis of apsidal EB motion.

[^4]: This assumption is fulfilled only partially. We can mention cyclical variations of instantaneous LCs with other than orbital period as the gradual change of the ES geometry due to asymptotic motion of double systems orbiting on eccentric orbits, possible asynchronous rotation of spotted components in wide systems, and possible pulsations of the components. Eclipsing binary light curves may also vary erratically because of chromospheric activity (see e.g. Sect. 6.4.3), time-dependent spottiness of the components, or changes in streams or disks around the stars. Neglecting of above mentioned effects introduce as a rule some extra noise in the period analyses and deteriorate the accuracy of the determination model parameters.

[^5]: If $p>q$ then $\sum_{k=p}^q\,h_k=0.$

[^6]: Wilson & Van Hamme (2014) used for modelling of phase function $\vartheta$ and its inversion $\mathit{\Theta}$ an exact solution of the basic equation, Eq. (1): $\vartheta(t)\!=\!\dot{P}^{-1}\ln \left[ 1+\dot{P}/P_0\,(t-M_0)\right]$, $\mathit{\Theta}(E)\!=\!P_0/\dot{P} \left[\exp(E \dot{P}-1)-1\right]+M_0$. Nevertheless, our models for $\vartheta$ and $\mathit{\Theta}$ (see Eqs. 17) do not differ by more than $1.9\times10^{-5}$ in the phase function and 0.3 s in time prediction from the exact ones. So they can be considered to be identical.

[^7]: We did not distinguish between primary and secondary light minima because their depths are nearly the same.

[^8]: All the eclipse times were given without quoting their uncertainties.

[^9]: The detailed study about the triple star AR Aur is in preparation. For formulae see Liška et al. (2015).


## Commented-out source text

*[manual review: the following lines are commented out in `brnoarxiv.tex` and are not part of the typeset paper.]*

> \subsection{Experiences with phenomenological modelling of eclipsing systems}
> We are convinced that p
> Nevertheless, the prepared statistical studies promise to find some correlations among the above mentioned and phenomenological parameters.
