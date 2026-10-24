; Скрипт Inno Setup: установщик GhostTranslate_v<версия>_Setup.exe (~290 МБ вместе с моделью перевода и RapidOCR)
#define MyAppName "GhostTranslate"
#define MyAppVersion "3.4"
#define MyAppPublisher "GhostTranslate AR Studio"
#define MyAppExeName "GhostTranslate.exe"

[Setup]
AppId={{8E327A7C-C82C-4A04-87C9-327805C4FDE5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_out
OutputBaseFilename=GhostTranslate_v{#MyAppVersion}_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
; Запущенную программу ловит мьютекс single_instance.MUTEX_NAME в секции [Code], а не AppMutex:
; при обновлении из программы она закрывается уже после старта установщика, и встроенная
; проверка в тихом режиме молча отменила бы установку вместо того, чтобы подождать.

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Библиотеки прошлой версии: от смены numpy, Qt или onnxruntime остаются чужие файлы.
Type: filesandordirs; Name: "{app}\_internal"
; В имени ярлыка версия: без этого после обновления остаётся и «v3.3», и «v3.4».
Type: files; Name: "{group}\{#MyAppName} v*.lnk"
Type: files; Name: "{autodesktop}\{#MyAppName} v*.lnk"

[Files]
Source: "dist\GhostTranslate\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\GhostTranslate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName} v{#MyAppVersion}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName} v{#MyAppVersion}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent shellexec
; Обновление из программы идёт с /SILENT, и строка выше пропускается.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait shellexec; Check: IsUpdate

[Code]
const
  AppMutexName = 'GhostTranslateSingleInstance';
  UpdateWaitSeconds = 30;

{ /UPDATE=1 передаёт ghosttranslate/updater.py. }
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function WaitForAppExit(Seconds: Integer): Boolean;
var
  I: Integer;
begin
  for I := 1 to Seconds * 4 do
  begin
    if not CheckForMutexes(AppMutexName) then
    begin
      Result := True;
      Exit;
    end;
    Sleep(250);
  end;
  Result := not CheckForMutexes(AppMutexName);
end;

function AskToCloseApp: Boolean;
begin
  Result := True;
  while CheckForMutexes(AppMutexName) do
    if SuppressibleMsgBox('GhostTranslate запущен. Закройте его: значок рядом с часами, пункт «Полный выход [X]». Затем нажмите OK.',
                          mbError, MB_OKCANCEL, IDCANCEL) <> IDOK then
    begin
      Result := False;
      Exit;
    end;
end;

function InitializeSetup: Boolean;
begin
  if IsUpdate and WaitForAppExit(UpdateWaitSeconds) then
    Result := True
  else
    Result := AskToCloseApp;
end;

function InitializeUninstall: Boolean;
begin
  Result := AskToCloseApp;
end;
