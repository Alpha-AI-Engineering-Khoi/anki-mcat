<!--
Bundled MCAT source document (Bio/Biochem :: Enzymes).
Real, accurate MCAT-relevant content used as the ground-truth source for the
Draft pipeline and the Card Check eval. Each paragraph is a span; the span id is
"S{n}" by paragraph order (see mcat_ai.load_source). Topic tag applies to the
whole file. Internal study tool only.
topic: MCAT::BioBiochem::Enzymes
-->

# Enzymes: structure, catalysis, and kinetics

Enzymes are biological catalysts, almost always proteins, that speed up a reaction by lowering its activation energy without being consumed and without changing the reaction's equilibrium position. They lower activation energy by stabilizing the transition state, the highest-energy arrangement on the reaction path.

An enzyme acts on a substrate, the molecule it binds and transforms. Binding occurs at the active site, a small pocket whose shape and chemistry are complementary to the transition state. The induced-fit model holds that the active site changes shape slightly as the substrate binds, improving catalysis, in contrast to the older lock-and-key model of a rigid site.

Many enzymes require a non-protein helper. A cofactor is an inorganic ion such as zinc or magnesium; a coenzyme is a small organic molecule, often derived from a vitamin, such as NAD+ or coenzyme A. The inactive protein alone is an apoenzyme, and the complete catalytically active enzyme with its cofactor is a holoenzyme. A tightly, often covalently bound cofactor is called a prosthetic group.

Enzyme activity depends on the environment. Each enzyme has an optimal pH and temperature at which its rate is highest; moving away from the optimum lowers activity, and extremes cause denaturation, the loss of three-dimensional structure and therefore function.

Michaelis-Menten kinetics describes how initial reaction rate depends on substrate concentration for many enzymes. The rate rises steeply at low substrate concentration and then levels off, approaching a maximum rate Vmax as the enzyme becomes saturated. The Michaelis constant Km is the substrate concentration at which the rate is half of Vmax; a low Km indicates high affinity of the enzyme for its substrate.

The turnover number kcat is the maximum number of substrate molecules one active site converts to product per unit time when the enzyme is saturated. The ratio kcat over Km measures catalytic efficiency and is useful for comparing how well an enzyme performs on different substrates.

A Lineweaver-Burk plot is the double-reciprocal linearization of the Michaelis-Menten equation, plotting one over rate against one over substrate concentration. Its y-intercept is one over Vmax and its x-intercept is negative one over Km, which makes it a common tool for distinguishing types of inhibition.

Competitive inhibitors resemble the substrate and bind the active site, so they raise the apparent Km while leaving Vmax unchanged, and their effect can be overcome by adding more substrate. Noncompetitive inhibitors bind an allosteric site whether or not substrate is present, lowering Vmax while leaving Km unchanged. Uncompetitive inhibitors bind only the enzyme-substrate complex, lowering both Km and Vmax. Mixed inhibitors bind free enzyme and the complex with different affinities and change both parameters.

Allosteric enzymes have multiple subunits and regulatory sites distinct from the active site. Binding of an activator or inhibitor at a regulatory site shifts the enzyme between a more active and a less active conformation, producing a sigmoidal rather than hyperbolic rate curve. This cooperativity means binding at one site changes affinity at others.

Cells regulate pathways through feedback inhibition, in which the final product of a pathway inhibits an enzyme acting early in that pathway, preventing wasteful overproduction. Enzymes are also controlled by reversible covalent modification such as phosphorylation, by proteolytic activation of inactive zymogens, and by changes in the amount of enzyme synthesized.
