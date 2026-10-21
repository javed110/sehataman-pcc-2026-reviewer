"""Read-only DOCX rendering fallback using installed Word on Windows.

Packaged LibreOffice is unavailable on this Windows bundle. Never saves the
source document. Macros, prompts and link updates are disabled.
"""
from pathlib import Path
import subprocess
import sys
import win32com.client

source=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
pdf=out/(source.stem+'.pdf')
app=win32com.client.DispatchEx('Word.Application')
try:
    app.Visible=False;app.DisplayAlerts=0;app.AutomationSecurity=3
    app.Options.UpdateLinksAtOpen=False
    doc=app.Documents.Open(str(source),ConfirmConversions=False,ReadOnly=True,AddToRecentFiles=False,Visible=False)
    try:doc.ExportAsFixedFormat(str(pdf),17,OpenAfterExport=False)
    finally:doc.Close(False)
finally:app.Quit(False)
poppler=Path(r'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe')
subprocess.run([str(poppler),'-r','110','-png',str(pdf),str(out/'page')],check=True)
print('Rendered',len(list(out.glob('page-*.png'))),'pages in',out)
