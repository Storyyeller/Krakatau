sealed interface Shape {}
record Circle(double radius) implements Shape {}
record Rect(double height, double width) implements Shape {}


class PatternMatching {
    static double area(Shape s) {
        return switch (s) {
            case Circle c -> c.radius() * c.radius() * 3.1415926;
            case Rect r -> r.height() * r.width();
        };
    }

    public static void main(String[] args) {
        Shape[] shapes = {new Circle(1.4), new Rect(4, 9)};

        for (Shape s: shapes) {
            System.out.println("Shape " + s + " has area " + area(s));
        }
    }
}
