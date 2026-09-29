import unittest

from fast_server.parsing import parse_camera_message, parse_imu_message


class ParsingTests(unittest.TestCase):

    def test_camera_invalid_topic(self):

        topic = "camera"
        payload = b"34234234234, 1, 2, 33, 44, 55, 66, 77, 88, image.py"

        with self.assertRaises(ValueError):
            parse_camera_message(topic, payload)

    def test_imu_invalid_topic(self):

        topic = "imu"
        payload = (
            b"1700779200.123, 0.1, 0.2, 0.3,"
            b" 1.0, 2.0, 3.0,"
            b" 0.01, 0.02, 0.03,"
            b" 10.0, 20.0, 30.0"
        )

        with self.assertRaises(ValueError):
            parse_imu_message(topic, payload)

    def test_camera_less_payload(self):
        topic = "camera/123"
        payload = b"34234234234, 1, 2"

        with self.assertRaises(ValueError):
            parse_camera_message(topic, payload)

    def test_imu_less_payload(self):

        topic = "imu/123"
        payload = (
            b"1700779200.123, 0.1, 0.2, 0.3,"
        )

        with self.assertRaises(ValueError):
            parse_imu_message(topic, payload)

    def test_camera_invalid_payload(self):
        topic = "camera/123"
        payload = b"text, s1, 2f, 33, 44, 55, 66, 77, 88, image.py"

        with self.assertRaises(ValueError):
            parse_camera_message(topic, payload)

    def test_imu_invalid_payload(self):
        topic = "imu/123"
        payload = (
            b"1700779200.123s, 0.1x, 0.2x, 0.3rs,"
            b" adasd, 2.0, 3.0,"
            b" 0.01, 0.02, 0.03,"
            b" 10.0, 20.0, 30.0"
        )

        with self.assertRaises(ValueError):
            parse_imu_message(topic, payload)

    def test_camera_valid(self):
        topic = "camera/123"
        payload = b"23242342342.9999, 3423423, 2, 33, 44, 55, 66, 77, 88, image.py"

        data = parse_camera_message(topic, payload)

        self.assertEqual(data["device_label"], "123")
        self.assertAlmostEqual(data["recorded_at"], 23242342342.9999, places=6)
        self.assertEqual(data["frame_idx"], 3423423)
        self.assertEqual(data["marker_idx"], 2)
        self.assertEqual(data["rvec_x"], 33)
        self.assertEqual(data["rvec_y"], 44)
        self.assertEqual(data["rvec_z"], 55)
        self.assertEqual(data["tvec_x"], 66)
        self.assertEqual(data["tvec_y"], 77)
        self.assertEqual(data["tvec_z"], 88)
        self.assertEqual(data["image_path"], "")

    def test_imu_valid(self):
        topic = "imu/123"
        payload = (
            b"1700779200.123, 0.1, 0.2, 0.3,"
            b" 7, 2.0, 3.0,"
            b" 0.01, 0.02, 0.03,"
            b" 10.0, 20.0, 30.0"
        )

        data = parse_imu_message(topic, payload)

        self.assertEqual(data["device_label"], "123")
        self.assertAlmostEqual(data["recorded_at"], 1700779200.123, places=6)
        self.assertEqual(data["accel_x"], 0.1)
        self.assertEqual(data["accel_y"], 0.2)
        self.assertEqual(data["accel_z"], 0.3)
        self.assertEqual(data["gyro_x"], 7)
        self.assertEqual(data["gyro_y"], 2.0)
        self.assertEqual(data["gyro_z"], 3.0)
        self.assertEqual(data["mag_x"], 0.01)
        self.assertEqual(data["mag_y"], 0.02)
        self.assertEqual(data["mag_z"], 0.03)
        self.assertEqual(data["yaw"], 10.0)
        self.assertEqual(data["pitch"], 20.0)
        self.assertEqual(data["roll"], 30.0)

    def test_camera_valid_extra(self):
        topic = "camera/123"
        payload = b"23242342342.9999, 3423423, 2, 33, 44, 55, 66, 77, 88, image.py, 33423423, otherstuff"

        data = parse_camera_message(topic, payload)

        self.assertEqual(data["device_label"], "123")
        self.assertAlmostEqual(data["recorded_at"], 23242342342.9999, places=6)
        self.assertEqual(data["frame_idx"], 3423423)
        self.assertEqual(data["marker_idx"], 2)
        self.assertEqual(data["rvec_x"], 33)
        self.assertEqual(data["rvec_y"], 44)
        self.assertEqual(data["rvec_z"], 55)
        self.assertEqual(data["tvec_x"], 66)
        self.assertEqual(data["tvec_y"], 77)
        self.assertEqual(data["tvec_z"], 88)
        self.assertEqual(data["image_path"], "")

    def test_imu_valid_extra(self):
        topic = "imu/123"
        payload = (
            b"1700779200.123, 0.1, 0.2, 0.3,"
            b" 7, 2.0, 3.0,"
            b" 0.01, 0.02, 0.03,"
            b" 10.0, 20.0, 30.0, 23423, sfsdf, 32"
        )

        data = parse_imu_message(topic, payload)

        self.assertEqual(data["device_label"], "123")
        self.assertAlmostEqual(data["recorded_at"], 1700779200.123, places=6)
        self.assertEqual(data["accel_x"], 0.1)
        self.assertEqual(data["accel_y"], 0.2)
        self.assertEqual(data["accel_z"], 0.3)
        self.assertEqual(data["gyro_x"], 7)
        self.assertEqual(data["gyro_y"], 2.0)
        self.assertEqual(data["gyro_z"], 3.0)
        self.assertEqual(data["mag_x"], 0.01)
        self.assertEqual(data["mag_y"], 0.02)
        self.assertEqual(data["mag_z"], 0.03)
        self.assertEqual(data["yaw"], 10.0)
        self.assertEqual(data["pitch"], 20.0)
        self.assertEqual(data["roll"], 30.0)

    def test_camera_valid_spaces(self):
        topic = "camera/123"
        payload = b"23242342342.9999,3423423,2, 33, 44                                          ,                     55,                       66, 77, 88, image.py"

        data = parse_camera_message(topic, payload)

        self.assertEqual(data["device_label"], "123")
        self.assertAlmostEqual(data["recorded_at"], 23242342342.9999, places=6)
        self.assertEqual(data["frame_idx"], 3423423)
        self.assertEqual(data["marker_idx"], 2)
        self.assertEqual(data["rvec_x"], 33)
        self.assertEqual(data["rvec_y"], 44)
        self.assertEqual(data["rvec_z"], 55)
        self.assertEqual(data["tvec_x"], 66)
        self.assertEqual(data["tvec_y"], 77)
        self.assertEqual(data["tvec_z"], 88)
        self.assertEqual(data["image_path"], "")

    def test_imu_valid_spaces(self):
        topic = "imu/123"
        payload = (
            b"1700779200.123                , 0.1,                            0.2, 0.3,"
            b"7,2.0,3.0,"
            b" 0.01, 0.02, 0.03,"
            b" 10.0, 20.0, 30.0"
        )

        data = parse_imu_message(topic, payload)

        self.assertEqual(data["device_label"], "123")
        self.assertAlmostEqual(data["recorded_at"], 1700779200.123, places=6)
        self.assertEqual(data["accel_x"], 0.1)
        self.assertEqual(data["accel_y"], 0.2)
        self.assertEqual(data["accel_z"], 0.3)
        self.assertEqual(data["gyro_x"], 7)
        self.assertEqual(data["gyro_y"], 2.0)
        self.assertEqual(data["gyro_z"], 3.0)
        self.assertEqual(data["mag_x"], 0.01)
        self.assertEqual(data["mag_y"], 0.02)
        self.assertEqual(data["mag_z"], 0.03)
        self.assertEqual(data["yaw"], 10.0)
        self.assertEqual(data["pitch"], 20.0)
        self.assertEqual(data["roll"], 30.0)


if __name__ == '__main__':
    unittest.main()
