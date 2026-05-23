def publish_states(self):

    for device in self.devices:

        topic = f"lab/{device.domain}/{device.id}/state"

        self.client.publish(
            topic,
            device.state_payload(),
            retain=True
        )
