module.exports = {
  apps: [
    {
      name: 'pm_system',
      script: '/home/user/pm_system/venv/bin/python',
      args: '/home/user/pm_system/app.py',
      cwd: '/home/user/pm_system',
      env: {
        FLASK_ENV: 'development',
        PORT: 3000,
        SECRET_KEY: 'pm-system-secret-2025',
        DATABASE_URL: 'sqlite:////home/user/pm_system/pm_system.db'
      },
      watch: false,
      instances: 1,
      exec_mode: 'fork',
      error_file: '/home/user/pm_system/logs/error.log',
      out_file: '/home/user/pm_system/logs/out.log',
    }
  ]
}
