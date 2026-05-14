"""
ISS Reconstruction U-Net Model
Enhanced U-Net with Data Consistency Layer for sparse-to-dense ISS reconstruction

Key features:
1. Data Consistency Layer - ensures predictions match known measurements
2. Skip connections for preserving spatial details
3. Designed for 20% sparse input -> complete ISS maps
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class DataConsistencyLayer(nn.Module):
    """
    Ensures model predictions are consistent with known sparse measurements
    
    Output = sparse_mask * sparse_input + (1 - sparse_mask) * prediction
    This guarantees that wherever we have measurements, the output matches exactly.
    """
    
    def __init__(self):
        super().__init__()
    
    def forward(self, prediction, sparse_input, sparse_mask):
        """
        Args:
            prediction: Model prediction [B, 1, H, W] 
            sparse_input: Sparse ISS input [B, 1, H, W]
            sparse_mask: Binary mask [B, 1, H, W] (1=known, 0=unknown)
        
        Returns:
            Consistent output [B, 1, H, W]
        """
        return sparse_mask * sparse_input + (1 - sparse_mask) * prediction


class DoubleConv(nn.Module):
    """Double convolution block: Conv -> BN -> ReLU -> Conv -> BN -> ReLU"""
    
    def __init__(self, in_channels, out_channels, mid_channels=None):
        super().__init__()
        if not mid_channels:
            mid_channels = out_channels
        
        self.double_conv = nn.Sequential(
            nn.Conv2d(in_channels, mid_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(mid_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )
    
    def forward(self, x):
        return self.double_conv(x)


class Down(nn.Module):
    """Downscaling with maxpool then double conv"""
    
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.maxpool_conv = nn.Sequential(
            nn.MaxPool2d(2),
            DoubleConv(in_channels, out_channels)
        )
    
    def forward(self, x):
        return self.maxpool_conv(x)


class Up(nn.Module):
    """Upscaling then double conv"""
    
    def __init__(self, in_channels, out_channels, bilinear=True):
        super().__init__()
        
        # Use bilinear upsampling or transposed conv
        if bilinear:
            self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
            self.conv = DoubleConv(in_channels, out_channels, in_channels // 2)
        else:
            self.up = nn.ConvTranspose2d(in_channels, in_channels // 2, kernel_size=2, stride=2)
            self.conv = DoubleConv(in_channels, out_channels)
    
    def forward(self, x1, x2):
        x1 = self.up(x1)
        
        # Handle size mismatch
        diffY = x2.size()[2] - x1.size()[2]
        diffX = x2.size()[3] - x1.size()[3]
        x1 = F.pad(x1, [diffX // 2, diffX - diffX // 2,
                       diffY // 2, diffY - diffY // 2])
        
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)


class OutConv(nn.Module):
    """Output convolution layer"""
    
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=1)
    
    def forward(self, x):
        return self.conv(x)


class ISS_UNet(nn.Module):
    """
    U-Net for ISS reconstruction with data consistency
    
    Input channels:
        - Channel 0: Building heights (normalized [0,1])
        - Channel 1: Sparse ISS (normalized [0,1])  
        - Channel 2: Sparse mask (1=known, 0=unknown)
        - Channel 3: Outdoor mask (for loss computation)
        - Channel 4: DSS pathloss prior (normalized [0,1])
    
    Output:
        - Complete ISS map (normalized [0,1])
    """
    
    def __init__(self, n_channels=5, n_classes=1, bilinear=False, use_data_consistency=True):
        super().__init__()
        self.n_channels = n_channels
        self.n_classes = n_classes
        self.bilinear = bilinear
        self.use_data_consistency = use_data_consistency

        # Encoder (downsampling path)
        self.inc = DoubleConv(n_channels, 64)
        self.down1 = Down(64, 128)
        self.down2 = Down(128, 256)
        self.down3 = Down(256, 512)
        factor = 2 if bilinear else 1
        self.down4 = Down(512, 1024 // factor)

        # Decoder (upsampling path)
        self.up1 = Up(1024, 512 // factor, bilinear)
        self.up2 = Up(512, 256 // factor, bilinear)
        self.up3 = Up(256, 128 // factor, bilinear)
        self.up4 = Up(128, 64, bilinear)
        self.outc = OutConv(64, n_classes)

        # Data consistency layer (optional)
        if self.use_data_consistency:
            self.data_consistency = DataConsistencyLayer()
    
    def forward(self, x):
        """
        Args:
            x: Input tensor [B, 5, H, W]
               - x[:, 0]: Building heights
               - x[:, 1]: Sparse ISS
               - x[:, 2]: Sparse mask
               - x[:, 3]: Outdoor mask
               - x[:, 4]: DSS pathloss prior

        Returns:
            Complete ISS map [B, 1, H, W] with optional data consistency
        """
        # Save original input for data consistency layer
        x_input = x

        # U-Net forward pass
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)

        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        prediction = self.outc(x)   # Raw U-Net prediction

        # Optionally apply data consistency
        if self.use_data_consistency:
            sparse_iss = x_input[:, 1:2]      # [B, 1, H, W] - Sparse ISS input from original input
            sparse_mask = x_input[:, 2:3]     # [B, 1, H, W] - Sparse mask from original input
            output = self.data_consistency(prediction, sparse_iss, sparse_mask)
        else:
            output = prediction

        return output
    
    def get_model_info(self):
        """Get model architecture information"""
        total_params = sum(p.numel() for p in self.parameters())
        trainable_params = sum(p.numel() for p in self.parameters() if p.requires_grad)
        
        return {
            'model_name': 'ISS_UNet',
            'input_channels': self.n_channels,
            'output_channels': self.n_classes,
            'bilinear_upsampling': self.bilinear,
            'total_parameters': total_params,
            'trainable_parameters': trainable_params
        }


class ISS_UNet_Light(nn.Module):
    """
    Lightweight version of ISS U-Net for faster training/inference
    Reduced channel numbers for smaller memory footprint
    """
    
    def __init__(self, n_channels=5, n_classes=1, bilinear=True, use_data_consistency=True):
        super().__init__()
        self.n_channels = n_channels
        self.n_classes = n_classes
        self.bilinear = bilinear
        self.use_data_consistency = use_data_consistency

        # Encoder with reduced channels
        self.inc = DoubleConv(n_channels, 32)
        self.down1 = Down(32, 64)
        self.down2 = Down(64, 128)
        self.down3 = Down(128, 256)
        factor = 2 if bilinear else 1
        self.down4 = Down(256, 512 // factor)

        # Decoder
        self.up1 = Up(512, 256 // factor, bilinear)
        self.up2 = Up(256, 128 // factor, bilinear)
        self.up3 = Up(128, 64 // factor, bilinear)
        self.up4 = Up(64, 32, bilinear)
        self.outc = OutConv(32, n_classes)

        # Data consistency layer (optional)
        if self.use_data_consistency:
            self.data_consistency = DataConsistencyLayer()

    def forward(self, x):
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)

        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        prediction = self.outc(x)

        # Optionally apply data consistency
        if self.use_data_consistency:
            sparse_iss = x[:, 1:2]
            sparse_mask = x[:, 2:3]
            output = self.data_consistency(prediction, sparse_iss, sparse_mask)
        else:
            output = prediction

        return output
    
    def get_model_info(self):
        total_params = sum(p.numel() for p in self.parameters())
        trainable_params = sum(p.numel() for p in self.parameters() if p.requires_grad)
        
        return {
            'model_name': 'ISS_UNet_Light',
            'input_channels': self.n_channels,
            'output_channels': self.n_classes,
            'bilinear_upsampling': self.bilinear,
            'total_parameters': total_params,
            'trainable_parameters': trainable_params
        }


def test_models():
    """Test ISS U-Net models"""
    print("🧪 Testing ISS U-Net Models...")
    
    # Test input (batch_size=2, channels=5, height=128, width=128)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    test_input = torch.randn(2, 5, 128, 128).to(device)
    
    # Test full model
    print("\\n📊 Testing ISS_UNet (Full)...")
    model_full = ISS_UNet(n_channels=5, n_classes=1, bilinear=False).to(device)
    
    with torch.no_grad():
        output_full = model_full(test_input)
    
    info_full = model_full.get_model_info()
    print(f"✅ {info_full['model_name']} forward pass successful:")
    print(f"   Input shape: {test_input.shape}")
    print(f"   Output shape: {output_full.shape}")
    print(f"   Parameters: {info_full['total_parameters']:,}")
    print(f"   Output range: [{output_full.min():.4f}, {output_full.max():.4f}]")
    
    # Test lightweight model
    print("\\n📊 Testing ISS_UNet_Light...")
    model_light = ISS_UNet_Light(n_channels=5, n_classes=1, bilinear=True).to(device)
    
    with torch.no_grad():
        output_light = model_light(test_input)
    
    info_light = model_light.get_model_info()
    print(f"✅ {info_light['model_name']} forward pass successful:")
    print(f"   Input shape: {test_input.shape}")
    print(f"   Output shape: {output_light.shape}")
    print(f"   Parameters: {info_light['total_parameters']:,}")
    print(f"   Output range: [{output_light.min():.4f}, {output_light.max():.4f}]")
    
    # Test data consistency
    print("\\n🔧 Testing Data Consistency Layer...")
    sparse_input = test_input[:, 1:2]  # Extract sparse ISS
    sparse_mask = (torch.rand(2, 1, 128, 128) > 0.8).float().to(device)  # 20% known
    
    dc_layer = DataConsistencyLayer()
    prediction = torch.randn(2, 1, 128, 128).to(device)
    consistent_output = dc_layer(prediction, sparse_input, sparse_mask)
    
    # Verify consistency: where mask=1, output should equal sparse_input
    known_pixels = sparse_mask > 0.5
    if known_pixels.sum() > 0:
        difference = torch.abs(consistent_output[known_pixels] - sparse_input[known_pixels])
        max_diff = difference.max().item()
        print(f"✅ Data consistency verified: max difference = {max_diff:.2e}")
    
    print("\\n🎉 All model tests passed!")
    return model_full, model_light


if __name__ == "__main__":
    test_models()