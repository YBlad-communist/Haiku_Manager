using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string project = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
            Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        string electron = Path.Combine(
            project, "node_modules", "electron", "dist", "electron.exe");

        if (!File.Exists(electron))
        {
            MessageBox.Show(
                "Не найден Electron.\n\n" +
                "Положи лаунчер в папку проекта Haiku_Manager и выполни:\n" +
                "npm install",
                "Джарвис",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }

        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = electron;
        start.WorkingDirectory = project;
        start.UseShellExecute = false;

        StringBuilder command = new StringBuilder(".");
        for (int i = 0; i < args.Length; i++)
        {
            command.Append(' ');
            command.Append(Quote(args[i]));
        }
        start.Arguments = command.ToString();

        try
        {
            Process.Start(start);
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(
                "Не удалось запустить приложение.\n\n" + error.Message,
                "Джарвис",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
