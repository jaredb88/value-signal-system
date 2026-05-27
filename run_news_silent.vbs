' Ejecuta run_news.bat sin abrir ventana de CMD
' Parametro 0 = ventana oculta, False = no esperar
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "C:\value-signal-local\repo\run_news.bat", 0, False
Set WshShell = Nothing
