#!/bin/bash
echo 'Configurando permisos para TC420 (0888:4000)...'
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="0888", ATTR{idProduct}=="4000", MODE="0666"' | sudo tee /etc/udev/rules.d/99-tc420.rules
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0888", ATTRS{idProduct}=="4000", MODE="0666"' | sudo tee -a /etc/udev/rules.d/99-tc420.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
echo '¡Permisos listos! Ya puedes usar el TC420 sin sudo.'
