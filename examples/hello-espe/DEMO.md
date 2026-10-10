# Hello ESPE

从一份干净的克隆走到一次能看见结果的运行。这条路径只加了样例和脚本，不改引擎。

## ESPE 是什么

RetractorDB 是边缘信号处理引擎（Edge Signal Processing Engine，下面写成 ESPE）。它处理的是等间隔的实时流：遥测、信号、IoT。三个程序分工是：`xretractor` 编译并一直执行 `.rql`，`xqry` 从共享内存读结果，`xtrdb` 查看落盘的二进制记录。

时序数据库把时间放在每个点上。点先存进去，查询时再按时间戳对齐、降采样、补洞。对齐发生在读的时候，间隔可以忽大忽小。

ESPE 把间隔放在流的声明上。`DECLARE ... STREAM wheel, 1/10` 的意思是：这条流从一开始就是每 1/10 秒一个记录，间隔是有理数。`SELECT` 从上电算到进程退出，每个输出槽都是已经对齐的一个记录。

## 为什么小车融合要用 Beatty 节拍

轮速 10 Hz、IMU 20 Hz，两条流不是同一个钟。用浮点时间戳做“找最近的点”，边界会漂：快的那路可能被丢掉一半，也可能被贴两次。

RQL 的 `#` 是 Beatty 交织（代码里叫 Hash，定义在 `src/include/SOperations.hpp`）：

- 轮速间隔 Da = 1/10，IMU 间隔 Db = 1/20
- z = Db / (Da + Db) = 1/3
- 第 i 个输出槽：`floor(i*z) == floor((i+1)*z)` 时取 IMU，否则取轮速
- 字是固定的：IMU, IMU, 轮速，然后重复
- 输出间隔 Dc = Da*Db / (Da+Db) = 1/30 秒，仍然严格等间隔

全程是整数比，没有浮点时间戳。

`+` 做的是对齐到更快的那只钟。慢的那一路用 `floor` 保持上一拍（零阶保持）。在这个例子里，输出跟 IMU 走，每 1/20 秒一条，轮速每两拍才换一个新值。这就是重采样。

`&` 和 `%` 把 `#` 拆回去。参数是被拿掉的那一路的间隔。仓库里的 `test/IntegrationTest/deinterleave_roundtrip` 锁的就是这件事：拆出来的字节和原来的源一样。

## 接到 Pi 小车：先出特征流，再交给 JEV

轮速和 IMU 先不要进决策。ESPE 在边上把它们收成一条特征流 `fused`：每个槽已经是“这一拍的轮速 + 这一拍的偏航”。

后面的 JEV（判断、事件、车辆动作：转、刹、记一次事件）只读这条流。它不再自己重采样，也不再猜两个时间戳是不是同一时刻。它看到的是排好节拍的事实。决策要换，特征流的节拍可以不动。

## 仓库里本来就有的入口

- `README.md` 的 “Running your first query”：`#` 和 `+`，数据来自 `/dev/urandom`。适合看它会一直跑，不适合核对节拍。
- `examples/python-model/hash.py`、`sum.py`：同一套有理数公式的草图。
- `examples/session-record-1/query.rql`：README 指向的现成查询。
- `test/IntegrationTest/deinterleave_roundtrip`：引擎上的比特级往返。
- `test/IntegrationTest/simple`：两路不同间隔，用 `+` 做算术。

`examples/hello-espe/` 把其中最短的一条收成新人能跑的目录：两路合成数、一份 `query.rql`、一个核对脚本。

## 路径 A：不编译，先看节拍

只要 Python 3。不需要 Conan，也不需要 GCC 14。这一步演示调度公式，不跑引擎二进制。公式和 `Hash` / `Add` 相同，并用上面那个 z=2/3 的测试向量做了自检。

```bash
cd examples/hello-espe
python3 oracle.py
```

成功时第一行是 `self-check: OK`。接着是一张表：`imu, imu, wheel` 重复，以及 `+` 下面轮速成对保持（1000 出现两次，然后 1001 出现两次）。

## 路径 B：用 xretractor 核对

Linux 上从源码构建需要 GCC 14+（`std::print`）。按 README 的 Option B：

```bash
scripts/buildrdb.sh toolchain
scripts/buildrdb.sh conan ninja debug
ninja -C build/Debug install
```

安装之后（`xretractor` 在 `PATH` 上，或仍在 `build/Debug` / `build/Release` 里）：

```bash
cd examples/hello-espe
./run.sh
```

脚本会先跑路径 A。找到二进制之后执行的就是这两条：

```bash
xretractor query.rql --name hello-espe -c
xretractor query.rql --name hello-espe -r -k -f -u
```

含义：实例名 `hello-espe`（不占用默认实例，也不把查询塞进已经在跑的 systemd 服务）；`-c` 只编译；`-r` 屏幕安静；`-k` 不等按键；`-f` 不跟墙钟等待（离线，节拍语义不变）；`-u` 读到源文件结尾就停，不把短文件再卷回去。

然后 `python3 oracle.py --check-engine` 用同一公式核对四个落盘流的二进制前缀（小端 `uint32`，和测试里的 `od -tu4` 一样）：

| 文件 | 内容 |
| --- | --- |
| `bus` | `#` 交织，周期 1/30 秒 |
| `fused` | `+` 对齐，每记录两个 `uint32`：保持后的轮速，然后 IMU |
| `wheel_back` | 从 `bus` 拆回的轮速 |
| `imu_back` | 从 `bus` 拆回的 IMU |

成功时最后一行是 `engine: OK`。找不到二进制时脚本仍以 0 退出，并打印 `engine: skipped (xretractor not found)`。那是路径 A，不是引擎核对。

引擎侧的完整证明是测试，不是这个目录：

```bash
cd build/Debug
ctest -R 'deinterleave_roundtrip|it_simple-run' -V
```

## 样例数据

`wheel.txt`：1000 起的整数，16 行，声明间隔 1/10 秒。`imu.txt`：1 起的整数，32 行，声明间隔 1/20 秒。两段盖住同一段 1.6 秒。数分得很开，交织结果一眼能认出是哪一路。
