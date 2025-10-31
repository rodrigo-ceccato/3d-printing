// --- Panel Parameters
plate_w = 220; //mm
plate_h = 80;
plate_t = 3;
corner_r = 3;

// --- Cutout parameters
edge = 8;
lcd_w = 80;
lcd_h = 50;
lcd_y = 0;
lcd_x = -plate_w/2 + edge + lcd_w/2;

// round rectangle
module rounded_plate(w, h, r, t) {
    linear_extrude(height=t)
        offset(r=r) offset(delta=-r) square([w,h], center= true);
}

// screw holes
module screw_holes(){
    
}

difference(){
    // base
    translate([0,0,0]) rounded_plate(plate_w, plate_h, corner_r, plate_t);
    
    // LCD
    translate([lcd_x, lcd_y, 0]) cube([lcd_w, lcd_h, plate_t+5], center=true);
    
    // rotary encoder cut
    translate([lcd_x + 65, lcd_y-10, -1])linear_extrude(height=5) circle(r=10);
}