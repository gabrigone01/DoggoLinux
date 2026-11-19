; Installer Windows (Inno Setup 6): iscc /DMyVersion=1.2.3 packaging\doggo.iss  ->  dist\Doggo-windows-setup.exe
; Si aspetta la build PyInstaller "onedir" in dist\Doggo\ e l'icona in build\icon.ico.
; Installa per l'utente corrente (niente admin), chiude i Doggo aperti e sostituisce le vecchie versioni.
#ifndef MyVersion
  #define MyVersion "1.0.0"
#endif

[Setup]
; AppId fisso: le nuove versioni aggiornano quella già installata invece di installarne una seconda
AppId={{B7C2E4A1-5D3F-4F8E-9A61-2C7D0E5B9F43}
AppName=Doggo
AppVersion={#MyVersion}
AppVerName=Doggo {#MyVersion}
AppPublisher=gabrigone01
AppPublisherURL=https://github.com/gabrigone01/DoggoLinux
DefaultDirName={localappdata}\Programs\Doggo
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Doggo-windows-setup
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\Doggo.exe
UninstallDisplayName=Doggo
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=force
RestartApplications=no

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; i file della versione precedente (PyInstaller cambia le librerie a ogni versione)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Doggo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Doggo"; Filename: "{app}\Doggo.exe"
Name: "{autodesktop}\Doggo"; Filename: "{app}\Doggo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Doggo.exe"; Description: "{cm:LaunchProgram,Doggo}"; Flags: nowait postinstall skipifsilent

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

// Chiude ogni Doggo aperto: versione installata e vecchio Doggo-windows.exe portatile
procedure KillDoggo;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Doggo.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Doggo-windows.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(800);  // Windows rilascia i file un attimo dopo la fine del processo
end;

// Percorso dell'exe scritto nell'avvio automatico (il valore è "C:\...\Doggo.exe", con o senza virgolette)
function AutostartExe(var Exe: String): Boolean;
begin
  Result := RegQueryStringValue(HKCU, RunKey, 'Doggo', Exe);
  if Result then
    Exe := RemoveQuotes(Trim(Exe));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillDoggo;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OldExe, NewExe: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  NewExe := ExpandConstant('{app}\Doggo.exe');
  if AutostartExe(OldExe) and (CompareText(OldExe, NewExe) <> 0) then
  begin
    // l'avvio automatico puntava a un vecchio Doggo: ora parte quello installato
    RegWriteStringValue(HKCU, RunKey, 'Doggo', '"' + NewExe + '"');
    // il vecchio exe portatile viene sostituito, solo se è davvero un Doggo*.exe
    if (Pos('doggo', Lowercase(ExtractFileName(OldExe))) = 1) and (CompareText(ExtractFileExt(OldExe), '.exe') = 0)
       and FileExists(OldExe) then
      DeleteFile(OldExe);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Exe: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    KillDoggo;
    if AutostartExe(Exe) and (CompareText(Exe, ExpandConstant('{app}\Doggo.exe')) = 0) then
      RegDeleteValue(HKCU, RunKey, 'Doggo');
  end;
  // le impostazioni (%APPDATA%\Doggo, con la chiave API) restano, come su Linux
end;
