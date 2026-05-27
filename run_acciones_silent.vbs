' run_acciones_silent.vbs
' Lanza run_acciones.bat de forma totalmente invisible (sin ventana CMD)
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\value-signal-local\repo\run_acciones.bat""", 0, False
