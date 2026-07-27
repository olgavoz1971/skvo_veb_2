import lightkurve as lk
import matplotlib.pyplot as plt
import numpy as np

def get_and_plot_lightcurve(target: str, sector: int, author: str):
    """
    Searches for, downloads, and plots a TESS light curve for a target 
    matching a specific sector and pipeline author.
    """
    print(f"Searching for '{target}' (Sector {sector}, Author: {author})...")
    
    # 1. Search MAST via Lightkurve using explicit parameters
    search_result = lk.search_lightcurve(
        target, 
        sector=sector, 
        author=author,
        mission="TESS"
    )
    
    if len(search_result) == 0:
        print(f"No light curves found matching {target} in Sector {sector} with author '{author}'.")
        return None
    
    print("Found matching product:")
    print(search_result)
    
    # 2. Download the specific light curve file
    # (If multiple files match, we download the first one)
    lc = search_result[0].download()
    
    if lc is None:
        print("Failed to download the light curve file.")
        return None

    print(f'TESS_mag = {lc.meta["TESSMAG"]}')
    if 'kspsap_flux'in lc.columns:
        lc['det_flux'] = lc['kspsap_flux']

    lc['mag'] = lc.meta.get("TESSMAG") - 2.5*np.log10(lc['sap_flux'])
    print(lc['sap_flux', 'det_flux', 'sap_bkg', 'mag'])
    lc.plot(column='det_flux')
    lc.plot(column='sap_flux')
    lc.to_fits(path=f"{target.lower().replace(' ', '_')}_sector{sector}_{author.lower().replace(' ','')}.fits",
        overwrite=True)
    # 3. Clean & normalize for visual clarity
    # QLP light curves are usually flux/ksps, so removing NaNs and normalizing is best practice
    # lc_clean = lc.remove_nans().normalize()

    # 4. Plot the time-series using Lightkurve's built-in plotting helper
    # fig, ax = plt.subplots(figsize=(10, 5))
    
    # lc.plot(
    #     ax=ax, 
    #     column="flux", 
    #     color="#1f77b4", 
    #     linewidth=0.8,
    #     label=f"{target} (Sector {sector} - {author})"
    # )
    
    # ax.set_title(f"TESS Light Curve: {target} | Sector {sector} ({author})", fontsize=12)
    # ax.set_xlabel("Time [BJD - 2457000]", fontsize=10)
    # ax.set_ylabel("Normalized Flux", fontsize=10)
    # ax.grid(True, linestyle="--", alpha=0.5)
    
    # plt.tight_layout()
    plt.show()
    
    return lc

if __name__ == "__main__":
    # Parameters for the test query
    TARGET_ID = "TIC 35119266"
    # SECTOR = 4
    # SECTOR = 30
    SECTOR = 97
    AUTHOR = "QLP"

    # Execute workflow
    lc_data = get_and_plot_lightcurve(
        target=TARGET_ID, 
        sector=SECTOR, 
        author=AUTHOR
    )
