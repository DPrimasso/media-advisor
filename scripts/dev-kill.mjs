import { execFileSync, execSync } from 'node:child_process';
import { platform } from 'node:os';

const ports = [3001, 3002, 5173, 5174];

if (platform() === 'win32') {
  const script = [
    '$ports=@(3001,3002,5173,5174);',
    '$pids=@();',
    'foreach($p in $ports){ try{ $pids += (Get-NetTCPConnection -LocalPort $p -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess) } catch {} };',
    '$pids = $pids | Sort-Object -Unique | Where-Object { $_ -gt 0 };',
    'foreach($procId in $pids){ try{ taskkill /F /T /PID $procId 2>$null | Out-Null } catch {} };',
    "if($pids.Count -gt 0){ Start-Sleep -Milliseconds 800; Write-Host ('Killed PIDs: ' + ($pids -join ',')) } else { Write-Host 'No dev ports to kill.' }",
  ].join(' ');
  try {
    execFileSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script], {
      stdio: 'inherit',
    });
  } catch {
    /* ignore */
  }
} else {
  for (const port of ports) {
    try {
      const out = execSync(`lsof -ti :${port}`, { encoding: 'utf8' });
      const pids = out
        .trim()
        .split(/\s+/)
        .filter((p) => /^\d+$/.test(p));
      for (const pid of pids) {
        try {
          execSync(`kill -9 ${pid}`, { stdio: 'ignore' });
        } catch {
          /* ignore */
        }
      }
    } catch {
      /* no listener or lsof error */
    }
  }
}
