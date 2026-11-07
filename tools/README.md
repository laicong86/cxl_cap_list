# tools/

在实验机上部署与运行 `cxl_dump.py` 的辅助脚本。**这些脚本不参与解析逻辑**，只是把文件传上去再执行，方便反复迭代。

密码一律通过环境变量传入，不写在文件里：

```bash
export CXL_HOST=192.0.2.10      # 目标主机
export CXL_USER=root
export CXL_PASS='...'           # 必填，无默认值
export CXL_BDF=0000:3b:00.0     # 可选，默认 0000:a8:00.0
```

## deploy_and_run.py

上传 `src/cxl_dump.py` 到远端 `/root/cxl/`，然后以指定 BDF 运行。需要 `pip install paramiko`。

```bash
python tools/deploy_and_run.py
```

## remote.py

通用远程执行 / 单文件上传，调试时用。

```bash
python tools/remote.py "lspci -s a8:00.0 -vvv"
python tools/remote.py -f src/cxl_dump.py /root/cxl/cxl_dump.py   # 上传
```

## run_on_host.sh

纯 POSIX shell 版本，**不需要 Python 或 paramiko**。适合在只能手工登录的场景用。

```bash
scp tools/run_on_host.sh root@<your-host>:/tmp/
ssh root@<your-host> 'sh /tmp/run_on_host.sh 0000:a8:00.0'
```

脚本会先校验 BDF 是否存在并打印 vendor/device/class/driver，再调用 dump；BDF 不存在时会把现有 CXL 设备列出来。
