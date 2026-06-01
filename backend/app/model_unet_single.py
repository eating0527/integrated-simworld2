import torch
import torch.nn as nn


class ConvBlock(nn.Module):
    """Conv -> BN -> ReLU -> Conv -> BN -> ReLU"""

    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.block(x)


class UNet(nn.Module):
    def __init__(self, in_channels=3, out_channels=1, features=(64, 128, 256, 512)):
        super().__init__()
        self.encoders = nn.ModuleList()
        self.pools = nn.ModuleList()
        prev_ch = in_channels
        for feature_count in features:
            self.encoders.append(ConvBlock(prev_ch, feature_count))
            self.pools.append(nn.MaxPool2d(2))
            prev_ch = feature_count

        self.bottleneck = ConvBlock(features[-1], features[-1] * 2)

        self.upconvs = nn.ModuleList()
        self.decoders = nn.ModuleList()
        prev_ch = features[-1] * 2
        for feature_count in reversed(features):
            self.upconvs.append(nn.ConvTranspose2d(prev_ch, feature_count, 2, stride=2))
            self.decoders.append(ConvBlock(feature_count * 2, feature_count))
            prev_ch = feature_count

        self.head = nn.Sequential(
            nn.Conv2d(features[0], out_channels, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        skips = []
        for encoder, pool in zip(self.encoders, self.pools):
            x = encoder(x)
            skips.append(x)
            x = pool(x)

        x = self.bottleneck(x)

        for upconv, decoder, skip in zip(self.upconvs, self.decoders, reversed(skips)):
            x = upconv(x)
            x = torch.cat([x, skip], dim=1)
            x = decoder(x)

        return self.head(x)
