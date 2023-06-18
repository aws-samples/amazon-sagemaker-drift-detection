import os

import matplotlib.pyplot as plt
import numpy as np
import sagemaker
from matplotlib.colors import rgb2hex
from pyvis.network import Network

sagemaker_session = sagemaker.Session()
sm_client = sagemaker_session.sagemaker_client

cmap = plt.get_cmap("Pastel2")
names = [
    "Approval",
    "DataSet",
    "Endpoint",
    "Image",
    "Model",
    "ModelGroup",
    "ModelDeployment",
    "ProcessingJob",
    "TrainingJob",
]
colors = {
    name: rgb2hex(color)
    for name, color in zip(names, cmap(np.linspace(0, 1, len(names))))
}


def create_legend_notes(net):
    # Add Legend Nodes
    step = 50
    x = -500
    y = -250
    legend_nodes = [
        dict(
            n_id=legend_node,
            label=label,
            # group=legend_node,
            physics=False,
            size=30,
            x=x,
            y=f"{y + legend_node*step}px",
            shape="box",
            font={"size": 20},
            color=colors[label],
            )
        for legend_node, label in enumerate(names)
    ]
    # print(legend_nodes)
    [net.add_node(**node) for node in legend_nodes]

    return


class Visualizer:
    def __init__(self):
        self.directory = "generated"
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)

    def render(self, query_lineage_response, scenario_name, height=600, width=1000):
        net = self.get_network(height=height, width=width)
        for vertex in query_lineage_response["Vertices"]:
            arn, label, name, title, lineage_type = self.process_vertex(vertex)
            if name.startswith("s3://"):
                name = f"{name.split('/')[-1]}\n{name}"

            net.add_node(
                arn,
                label=label + "\n" + lineage_type,
                title=name if name else title,
                shape="circle",
                color=colors[label],
            )

        create_legend_notes(net)

        for edge in query_lineage_response["Edges"]:
            source = edge["SourceArn"]
            dest = edge["DestinationArn"]
            net.add_edge(dest, source)

        return net.show(f"{self.directory}/{scenario_name}.html")

    def get_title(self, arn):
        return f"Arn: {arn}"

    def get_name(self, arn, lineage_type=None):
        name = arn.split("/")[1]
        return name

    def process_vertex(self, vertex):
        arn = vertex["Arn"]
        if "Type" in vertex:
            label = vertex["Type"]
        else:
            label = None
        lineage_type = vertex["LineageType"]
        name = arn.split("/")[1]
        if lineage_type in ["Artifact", "DataSet"]:
            name = (
                sm_client.describe_artifact(ArtifactArn=arn)
                .get("Source")
                .get("SourceUri")
            )
            if isinstance(name, list):
                name = name[0]
            if name.startswith("arn"):
                name = name.split("/")[1]

        title = f"Artifact Arn: {arn}"
        return arn, label, name, title, lineage_type

    def get_network(self, height: int = 600, width: int = 1000):
        net = Network(
            height=f"{height}px",
            width=f"{width}px",
            directed=True,
            notebook=True,
            cdn_resources="in_line",
        )
        net.set_options(
            """
        var options = {
  "nodes": {
    "borderWidth": 3,
    "shadow": {
      "enabled": true
    },
    "shapeProperties": {
      "borderRadius": 3
    },
    "size": 11,
    "shape": "circle"
  },
  "edges": {
    "arrows": {
      "to": {
        "enabled": true
      }
    },
    "color": {
      "inherit": true
    },
    "smooth": false
  },
  "layout": {
    "hierarchical": {
      "enabled": false,
      "direction": "LR",
      "sortMethod": "directed"
    }
  },
  "physics": {
    "hierarchicalRepulsion": {
      "centralGravity": 0
    },
    "minVelocity": 0.75,
    "solver": "hierarchicalRepulsion"
  }
}
        """
        )
        return net
