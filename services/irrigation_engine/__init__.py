"""Modele d'analyse de plantation et d'optimisation de l'irrigation (economie d'eau)."""

from pathlib import Path
import json


def analyser_terrain(config, sortie="resultats"):
    """Pipeline complet. config : chemin JSON ou dict. Retourne le dict de resultats."""
    from .image_analysis import Terrain
    from .design import Conception
    from .diagnose import analyser
    from .drawing import dessin_existant, plan_optimal, graphique_mensuel
    from .report import rapport_html, exports

    if not isinstance(config, dict):
        p = Path(config)
        cfg = json.loads(p.read_text(encoding="utf-8"))
        for k in ("image", "image_zones"):
            if cfg.get(k) and not Path(cfg[k]).is_absolute():
                cfg[k] = str(p.parent / cfg[k])
    else:
        cfg = config
    out = Path(sortie)
    out.mkdir(parents=True, exist_ok=True)
    T = Terrain(cfg).run()
    C = Conception(T).run()
    res = analyser(cfg, T, C)
    imgs = {
        "existant": out / "1_analyse_existant.png",
        "plan": out / "2_plan_optimal.png",
        "mensuel": out / "3_besoins_mensuels.png",
    }
    dessin_existant(T, imgs["existant"])
    plan_optimal(T, C, imgs["plan"])
    graphique_mensuel(res["bilan"], imgs["mensuel"])
    rapport_html(cfg, T, C, res, imgs, out / "rapport.html")
    exports(res, C, out)
    res["avertissements"] = T.warnings
    return res
