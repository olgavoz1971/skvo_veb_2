"""Optional matplotlib debug plots for offline GP pipeline runs."""

import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({"font.size": 24})


def plot_GP_results(
    x, y_norm, noise_sigma_norm,
    jd_peak, mean_peak, peaks_jd, jd_max_guess, jd_peak_std,
    jd_grid, mean_grid, std_grid, n_samples_uncert,
):
    """Matplotlib summary of a GP fit (development use only)."""
    plt.figure(figsize=(16, 10))
    plt.errorbar(
        x, y_norm, yerr=noise_sigma_norm, fmt="o", markersize=6,
        ecolor="gray", elinewidth=1, capsize=2,
        label="data (with estimated errors)",
    )
    plt.scatter(x, y_norm, s=30, color="k")
    plt.plot(jd_grid.ravel(), mean_grid.ravel(), color="tab:blue", lw=2, label="GP mean")
    plt.fill_between(
        jd_grid.ravel(),
        mean_grid.ravel() - std_grid.ravel(),
        mean_grid.ravel() + std_grid.ravel(),
        color="tab:blue", alpha=0.25, label="GP ±1σ",
    )
    plt.scatter(
        peaks_jd, np.full_like(peaks_jd, 0.98 * mean_peak),
        s=30, color="orange", alpha=0.1,
        label=f"Posterior peak draws (n={n_samples_uncert})",
    )
    if jd_max_guess is not None:
        plt.axvline(jd_max_guess, color="green", linestyle=":", lw=1.5, label="Peak guess")
    plt.axvline(float(jd_peak - jd_peak_std), color="magenta", linestyle=":", lw=2)
    plt.axvline(float(jd_peak), color="magenta", linestyle="--", lw=2, label=f"GP peak: {jd_peak:.8f}")
    plt.axvline(float(jd_peak + jd_peak_std), color="magenta", linestyle=":", lw=2)
    plt.fill_betweenx(
        [plt.ylim()[0], plt.ylim()[1]],
        float(jd_peak - jd_peak_std),
        float(jd_peak + jd_peak_std),
        color="magenta", alpha=0.1, label="±1σ range",
    )
    plt.xlabel("JD")
    plt.ylabel("Normalised flux")
    plt.title("GP fit and peak estimate")
    plt.legend(fontsize=14)
    plt.show()


def plot_GP_sampling_demo(x, y_norm, noise_sigma_norm, jd_grid, mean_grid, std_grid, samples, extr_jds, extrema_mode):
    """Illustrates posterior sampling (development use only)."""
    plt.figure(figsize=(16, 10))
    plt.errorbar(
        x, y_norm, yerr=noise_sigma_norm, fmt="o", color="black",
        alpha=0.4, label="Observations (Normalised)",
    )
    plt.plot(jd_grid, mean_grid, color="tab:blue", lw=3, label="GP Mean (Most Probable)")
    num_draws = min(300, samples.shape[1])
    for i in range(num_draws):
        label = "Posterior Realisations" if i == 0 else None
        plt.plot(jd_grid, samples[:, i], lw=0.5, alpha=0.3, label=label)
        if extrema_mode == "max":
            idx = np.argmax(samples[:, i])
        else:
            idx = np.argmin(samples[:, i])
        plt.scatter(jd_grid[idx], samples[idx, i], color="red", s=20, zorder=5)
    plt.title("GP Realisations Demo", fontsize=16)
    plt.xlabel("JD")
    plt.ylabel("Normalised Flux")
    plt.legend(loc="best", fontsize=12)
    plt.grid(alpha=0.3)
    plt.show()
