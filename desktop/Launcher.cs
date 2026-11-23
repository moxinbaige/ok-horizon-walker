using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyInformationalVersion("1.0.0")]

internal static class Launcher {
    [STAThread]
    private static int Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        if (!File.Exists(python)) python = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        string script = Path.Combine(root, "main.py");
        if (!File.Exists(python) || !File.Exists(script)) {
            MessageBox.Show("运行文件不完整，请将整个应用文件夹解压后重试。", "每日助手无法启动",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        try {
            var info = new ProcessStartInfo(python, "\"" + script + "\"");
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process.Start(info);
            return 0;
        } catch (Exception error) {
            MessageBox.Show(error.Message, "每日助手启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
