"""Batch 2 domain lists: batch1 domains + extra official hosts (incl. official hosts already seen in each Hub repo)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
_COLLECTORS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors")))
from domains import C as C1
EXTRA = {
 "GQ": ("Equatorial Guinea", "es", ["boe.gob.gq","gob.gq","minexteriores.gob.gq","minfuncionpublica.gob.gq","anticorrupcion.gob.gq","minhacienda.gob.gq","mintrabajo.gob.gq","guineaecuatorialpress.com"]),
 "ST": ("Sao Tome and Principe", "pt", ["gov.st","justica.gov.st","financas.gov.st","presidencia.st","bcstp.st","ine.st","assembleia.st","anstp.st","parlamento.st"]),
 "NG": ("Nigeria", "en", ["nass.gov.ng","justice.gov.ng","nigeriarights.gov.ng","statehouse.gov.ng","firs.gov.ng","cbn.gov.ng","sec.gov.ng","ncc.gov.ng","nerc.gov.ng","pencom.gov.ng","naicom.gov.ng","nesrea.gov.ng","ndpc.gov.ng","gov.ng"]),
 "EG": ("Egypt", "ar", ["alamiria.com","presidency.eg","parliament.gov.eg","cabinet.gov.eg","moj.gov.eg","cbe.org.eg","fra.gov.eg","eta.gov.eg","gafi.gov.eg","mof.gov.eg","gov.eg"]),
 "SA": ("Saudi Arabia", "ar", ["laws.boe.gov.sa","boe.gov.sa","uqn.gov.sa","ncar.gov.sa","sama.gov.sa","cma.org.sa","zatca.gov.sa","shura.gov.sa","moj.gov.sa","hrsd.gov.sa","sdaia.gov.sa","gov.sa"]),
 "ER": ("Eritrea", "en", ["shabait.com","moi.gov.er","mof.gov.er","gov.er"]),
}
C = dict(C1); C.update(EXTRA)
